"""Shared fakes for the storage and daily-job tests."""

import hashlib
import io
from pathlib import Path

from pipeline.store import LocalStore


class FakeS3:
    """Just enough of a boto3 S3 client, over a dict."""

    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.objects: dict[tuple[str, str], dict] = {}
        self.puts: list[str] = []
        self.delete_calls: list[int] = []

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl):  # noqa: N803
        self.objects[(Bucket, Key)] = {"body": Body, "type": ContentType, "cache": CacheControl}
        self.puts.append(Key)

    def get_object(self, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)]["body"])}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix):  # noqa: N803
                keys = sorted(k for b, k in client.objects if b == Bucket and k.startswith(Prefix))
                for i in range(0, max(len(keys), 1), 2):  # two keys a page, to exercise paging
                    yield {
                        "Contents": [
                            {
                                "Key": k,
                                "Size": len(client.objects[(Bucket, k)]["body"]),
                                "ETag": '"'
                                + hashlib.md5(client.objects[(Bucket, k)]["body"]).hexdigest()
                                + '"',
                            }
                            for k in keys[i : i + 2]
                        ]
                    }

        return Paginator()

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        self.delete_calls.append(len(Delete["Objects"]))
        for o in Delete["Objects"]:
            self.objects.pop((Bucket, o["Key"]), None)


class RecordingStore(LocalStore):
    """A LocalStore that records its puts and deletes, and can fail on a chosen put."""

    def __init__(self, root: Path, fail_on: str | None = None):
        super().__init__(root)
        self.puts: list[str] = []
        self.deleted: list[str] = []
        self.fail_on = fail_on

    def put(self, key, src):
        if key == self.fail_on:
            raise OSError(f"simulated failure writing {key}")
        self.puts.append(key)
        super().put(key, src)

    def delete(self, keys):
        self.deleted.extend(keys)
        super().delete(keys)


def make_out(root: Path, dates: list[str], layers=("olr", "wind10"), tag: str = "a") -> Path:
    """A small data root shaped like `./out`. A date's files depend only on the date; `tag`
    changes the series and the manifest, as a new day's run would."""
    import json

    def w(rel: str, data: bytes) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    for d in dates:
        for lid in layers:
            w(f"fields/{d}/{lid}.png", f"{d}-{lid}".encode())  # a date's files never change
        w(f"fields/{d}/wind10_uv.png", b"uv")
        w(f"fields/{d}/olr_anom.png", b"anom")
        w(f"points/{d}/0_0.bin", f"{d}-points".encode())
    for lid in layers:
        w(f"series/{lid}/0_0.bin", f"{tag}-series-{lid}".encode())
    w("clim/clim.json", b'{"period": "1991-2020"}')
    w("clim/01/olr.png", b"clim-01")
    w("clim/02/olr.png", b"clim-02")
    w("clim/series/olr/0_0.bin", b"clim-series")
    w("logs/global_means.csv", f"date,status\n{dates[-1]},ok\n".encode())
    manifest = {"dates": dates, "built_layers": sorted(layers), "built_at": tag}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root
