"""One-off: add the surface net longwave flux (`lw_up`) to tidy files built without it.

`net_sfc` needs ERA5 `str`, which the first 90 days were built without, and their raw
archives are long pruned. This fetches `str` alone (one request per month of dates, a cost of
at most 31 against the CDS limit of 400), and merges it into each date's tidy file through the
same conversion as the daily data (`convert.tidy_dataset`: J m-2 -> W m-2, sign flipped,
regridded). Archives and request IDs live in `raw/lw/`, apart from the daily fetch's state.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import xarray as xr

from .convert import area_weighted_mean, tidy_dataset
from .fetch import (
    _FAILED,
    SINGLE_DAILY,
    FetchSpec,
    _check_date,
    _load_state,
    _save_state,
    chunk_dates,
    split_archive,
    submit,
)
from .load import load_raw_archive
from .tidy import write_tidy

NAME = "single_str"
CDS_NAME = "surface_net_thermal_radiation"
MAX_QUEUED = 2
LW_UP_RANGE = (30.0, 100.0)  # W m-2, global mean; ERA5 is about 50-60

_TIDY = re.compile(r"^tidy_(\d{4}-\d{2}-\d{2})\.nc$")


def str_request(chunk: list[date]) -> FetchSpec:
    """One request for consecutive days within one month."""
    first, last = chunk[0], chunk[-1]
    if (first.year, first.month) != (last.year, last.month):
        raise ValueError("a chunk must lie within one month")
    request = {
        "product_type": "reanalysis",
        "variable": [CDS_NAME],
        "year": f"{first.year:04d}",
        "month": f"{first.month:02d}",
        "day": [f"{d.day:02d}" for d in chunk],
        "daily_statistic": "daily_sum",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
    }
    return FetchSpec(NAME, SINGLE_DAILY, request, f"{NAME}_{first}_{last}.nc")


def _archive(raw_dir: Path, day: date) -> Path:
    return raw_dir / "lw" / f"{NAME}_{day}.nc"


def fetch_str(c, days, raw_dir: Path, max_queued: int = MAX_QUEUED) -> list[str]:
    """Advance the `str` downloads by one step without waiting; returns the requests pending.

    Collects finished requests (split into `raw/lw/single_str_{date}.nc`), forgets failed ones,
    then submits the oldest missing months, at most `max_queued` at once (the CDS rejects more).
    """
    days = sorted(set(map(_check_date, days)))
    lw = raw_dir / "lw"
    lw.mkdir(parents=True, exist_ok=True)
    state_path = lw / "pending.json"
    state = _load_state(state_path)

    for key, job in list(state.items()):
        st = c.get_remote(job["id"]).status
        if st == "successful":
            chunk = lw / key
            part = chunk.with_name(chunk.name + ".part")
            c.get_remote(job["id"]).download(str(part))
            part.replace(chunk)
            split_archive(chunk, NAME, lw)
            chunk.unlink()
            del state[key]
        elif st in _FAILED:
            del state[key]
        _save_state(state_path, state)

    covered = {d for job in state.values() for d in job["days"]}
    missing = [
        d for d in days if not _archive(raw_dir, d).exists() and d.isoformat() not in covered
    ]
    for chunk in chunk_dates(missing):
        if len(state) >= max_queued:
            break
        spec = str_request(chunk)
        state[spec.filename] = {
            "id": submit(c, spec),
            "name": NAME,
            "days": [d.isoformat() for d in chunk],
        }
        _save_state(state_path, state)
    return sorted(state)


def dates_needing_lw_up(work_dir: Path) -> list[date]:
    """Dates with a tidy file that has no `lw_up`, oldest first."""
    found = []
    for p in sorted(work_dir.glob("tidy_*.nc")):
        m = _TIDY.match(p.name)
        if m is None:
            continue
        with xr.open_dataset(p) as ds:
            if "lw_up" not in ds:
                found.append(date.fromisoformat(m.group(1)))
    return found


def add_lw_up(day: date, raw_dir: Path, work_dir: Path) -> bool:
    """Merge a date's `str` archive into its tidy file as `lw_up`. Returns False when there is
    nothing to do (no archive yet, or the tidy file already has it); raises, changing nothing,
    when the global mean is implausible (a units or sign mistake)."""
    archive, tidy_path = _archive(raw_dir, day), work_dir / f"tidy_{day}.nc"
    if not archive.is_file():
        return False
    tidy = xr.load_dataset(tidy_path)
    if "lw_up" in tidy:
        return False
    lw = tidy_dataset({"str": load_raw_archive(archive)["str"]}, day.isoformat())["lw_up"]
    mean = area_weighted_mean(lw)
    if not LW_UP_RANGE[0] <= mean <= LW_UP_RANGE[1]:
        raise ValueError(
            f"{day}: lw_up global mean {mean:.1f} W m-2 outside "
            f"{LW_UP_RANGE[0]:g}-{LW_UP_RANGE[1]:g}"
        )
    tidy["lw_up"] = lw.astype("float64")
    write_tidy(tidy, work_dir)
    return True


def backfill_lw_up(
    c,
    work_dir: Path,
    raw_dir: Path,
    wait: bool = False,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, int]:
    """Fetch `str` for every tidy date lacking it and merge it in. With `wait`, polls (60 s,
    x1.5, at most 600 s) until done. Returns (dates updated, dates still without)."""
    updated, delay = 0, 60.0
    while True:
        needed = dates_needing_lw_up(work_dir)
        pending = fetch_str(c, needed, raw_dir)
        for day in needed:
            if add_lw_up(day, raw_dir, work_dir):
                updated += 1
                log(f"{day}: lw_up added")
        left = len(dates_needing_lw_up(work_dir))
        log(f"{left} date(s) still without lw_up; {len(pending)} request(s) pending")
        if not wait or left == 0:
            return updated, left
        sleep(delay)
        delay = min(delay * 1.5, 600.0)
