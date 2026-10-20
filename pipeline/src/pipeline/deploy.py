"""Move the data root between a working directory and object storage.

`upload` publishes `./out` to a store without ever leaving it half-updated: the map and point
files go up first, then the series, then the log, and the manifest, which is what the front
end reads first, goes up last. A failure before that leaves yesterday's site exactly as it
was (the new files are unreferenced extras). Only after the new manifest is in place are the
files of dates that fell out of the 90-day window deleted.

`download_state` brings back what a daily run needs from the store: the manifest, the
validation log, the in-flight CDS requests, the climatology, and the scalar maps of the
published dates (from which the series are rebuilt).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .store import Store, file_md5

MANIFEST = "manifest.json"
STATE_KEY = "state/pending.json"
LOG_KEY = "logs/global_means.csv"
WORKERS = 16
_CLIM_MAP = re.compile(r"clim/\d\d/\w+\.png")


@dataclass
class UploadResult:
    uploaded: int = 0
    skipped: int = 0
    deleted: int = 0


def _local(out: Path, subdir: str) -> dict[str, Path]:
    root = out / subdir
    if not root.is_dir():
        return {}
    found = (p for p in root.rglob("*") if p.is_file() and p.suffix != ".tmp")
    return {p.relative_to(out).as_posix(): p for p in found}


def _put_changed(
    store: Store, files: dict[str, Path], remote: dict, workers: int
) -> tuple[int, int]:
    """Upload the files that differ from what the store has. Returns (uploaded, skipped)."""
    changed = [
        k for k, p in files.items()
        if k not in remote or remote[k].size != p.stat().st_size or remote[k].md5 != file_md5(p)
    ]  # fmt: skip
    with ThreadPoolExecutor(workers) as pool:
        for _ in pool.map(lambda k: store.put(k, files[k]), changed):
            pass  # iterating re-raises the first failure
    return len(changed), len(files) - len(changed)


def upload(
    store: Store,
    out: Path,
    log: Callable[[str], None] = lambda _m: None,
    workers: int = WORKERS,
) -> UploadResult:
    """Publish `out` to `store`, manifest last, then delete files of expired dates."""
    manifest_path = out / MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{manifest_path} does not exist: nothing to publish")
    manifest = json.loads(manifest_path.read_text())
    remote = store.list("")
    result = UploadResult()
    maps = {**_local(out, "fields"), **_local(out, "points"), **_local(out, "clim")}
    stages = [
        ("maps, points and climatology", maps),
        ("series", _local(out, "series")),
        ("validation log", {k: p for k, p in _local(out, "logs").items() if k == LOG_KEY}),
    ]  # fmt: skip
    for name, files in stages:
        n, skipped = _put_changed(store, files, remote, workers)
        result.uploaded += n
        result.skipped += skipped
        log(f"{name}: {n} uploaded, {skipped} unchanged")
    store.put(MANIFEST, manifest_path)  # last: until now the old site was untouched
    result.uploaded += 1
    keep = set(manifest["dates"])
    expired = [
        k for k in remote
        if k.split("/", 1)[0] in ("fields", "points") and k.split("/")[1] not in keep
    ]  # fmt: skip
    store.delete(expired)
    result.deleted = len(expired)
    n_dates = len(manifest["dates"])
    log(f"manifest published ({n_dates} dates); {len(expired)} expired files deleted")
    return result


def upload_state(store: Store, raw: Path) -> bool:
    """Save the in-flight CDS request IDs. Returns False if there are none to save."""
    path = raw / "pending.json"
    if not path.is_file():
        return False
    store.put(STATE_KEY, path)
    return True


def _download(store: Store, keys: Iterable[str], out: Path, workers: int) -> int:
    keys = list(keys)
    with ThreadPoolExecutor(workers) as pool:
        got = list(pool.map(lambda k: store.get(k, out / k), keys))
    return sum(got)


def download_state(
    store: Store,
    raw: Path,
    out: Path,
    log: Callable[[str], None] = lambda _m: None,
    workers: int = WORKERS,
) -> dict | None:
    """Fetch what a daily run needs. Returns the stored manifest, or None for an empty store."""
    if not store.get(MANIFEST, out / MANIFEST):
        log("the store has no manifest yet: starting from nothing")
        return None
    manifest = json.loads((out / MANIFEST).read_text())
    store.get(STATE_KEY, raw / "pending.json")
    store.get(LOG_KEY, out / LOG_KEY)
    # The index and the monthly maps (anomalies need them); not clim/series, the chart's tiles.
    clim = [k for k in store.list("clim/") if k == "clim/clim.json" or _CLIM_MAP.fullmatch(k)]
    n_clim = _download(store, clim, out, workers)
    scalars = [
        f"fields/{d}/{layer}.png" for d in manifest["dates"] for layer in manifest["built_layers"]
    ]
    n_maps = _download(store, scalars, out, workers)
    n_dates = len(manifest["dates"])
    log(f"downloaded {n_maps} maps of {n_dates} dates and {n_clim} climatology files")
    return manifest
