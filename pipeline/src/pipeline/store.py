"""Object storage for the published data root.

The same layout as `./out` lives in a bucket. `S3Store` speaks the S3 API, so it works with
Cloudflare R2, AWS S3 and anything compatible; `LocalStore` is a folder with the same
interface, used by the tests and for dry runs (`--store file:///some/dir`).

Credentials and the endpoint come from the usual AWS environment variables
(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL for R2, AWS_DEFAULT_REGION=auto).
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    md5: str  # hex digest of the content, which is the ETag of a single-part upload


class Store(Protocol):
    def list(self, prefix: str = "") -> dict[str, ObjectInfo]: ...

    def get(self, key: str, dest: Path) -> bool:
        """Download an object to `dest`; False if it does not exist."""
        ...

    def put(self, key: str, src: Path) -> None: ...

    def delete(self, keys: Sequence[str]) -> None: ...


# How long a browser or CDN may reuse an object. The manifest is what the front end reads
# first, so it is never cached; per-date files only change if a date is rebuilt.
CACHE_RULES: tuple[tuple[str, str], ...] = (
    ("manifest.json", "no-cache"),
    ("state/", "no-store"),
    ("logs/", "no-cache"),
    ("clim/", "public, max-age=86400"),
    ("fields/", "public, max-age=3600"),
    ("points/", "public, max-age=3600"),
    ("series/", "public, max-age=3600"),
)


def cache_control(key: str) -> str:
    return next((value for prefix, value in CACHE_RULES if key.startswith(prefix)), "no-cache")


def content_type(key: str) -> str:
    if key.endswith(".bin"):
        return "application/octet-stream"
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


def file_md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class LocalStore:
    """A folder standing in for a bucket."""

    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"key escapes the store: {key!r}")
        return path

    def list(self, prefix: str = "") -> dict[str, ObjectInfo]:
        out: dict[str, ObjectInfo] = {}
        if not self.root.is_dir():
            return out
        for p in self.root.rglob("*"):
            if p.is_file() and not p.name.endswith(".tmp"):
                key = p.relative_to(self.root).as_posix()
                if key.startswith(prefix):
                    out[key] = ObjectInfo(p.stat().st_size, file_md5(p))
        return out

    def get(self, key: str, dest: Path) -> bool:
        src = self._path(key)
        if not src.is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(src.read_bytes())
        os.replace(tmp, dest)
        return True

    def put(self, key: str, src: Path) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(src.read_bytes())
        os.replace(tmp, dest)  # a reader sees the old or the new object, never half of one

    def delete(self, keys: Sequence[str]) -> None:
        for key in keys:
            path = self._path(key)
            path.unlink(missing_ok=True)
            for parent in path.parents:  # a bucket has no folders: drop the ones left empty
                if parent == self.root.resolve() or any(parent.iterdir()):
                    break
                parent.rmdir()


class S3Store:
    """A bucket (and optional key prefix) through a boto3 S3 client."""

    def __init__(self, client: Any, bucket: str, prefix: str = ""):
        self.client, self.bucket = client, bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""

    def list(self, prefix: str = "") -> dict[str, ObjectInfo]:
        out: dict[str, ObjectInfo] = {}
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self.prefix + prefix
        )
        for page in pages:
            for obj in page.get("Contents", []):
                out[obj["Key"][len(self.prefix) :]] = ObjectInfo(
                    obj["Size"], obj["ETag"].strip('"')
                )
        return out

    def get(self, key: str, dest: Path) -> bool:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"]
        except self.client.exceptions.NoSuchKey:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(body.read())
        os.replace(tmp, dest)
        return True

    def put(self, key: str, src: Path) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.prefix + key,
            Body=src.read_bytes(),
            ContentType=content_type(key),
            CacheControl=cache_control(key),
        )

    def delete(self, keys: Sequence[str]) -> None:
        for i in range(0, len(keys), 1000):  # the API takes at most 1000 keys at a time
            batch = [{"Key": self.prefix + k} for k in keys[i : i + 1000]]
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})


def open_store(url: str, client: Any = None) -> Store:
    """`file:///path` -> LocalStore; `s3://bucket[/prefix]` -> S3Store (needs boto3)."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return LocalStore(Path(parsed.path))
    if parsed.scheme == "s3" and parsed.netloc:
        if client is None:
            import boto3  # only needed for real buckets

            client = boto3.client("s3")
        return S3Store(client, parsed.netloc, parsed.path)
    raise ValueError(f"store URL must be file:///dir or s3://bucket[/prefix], got {url!r}")
