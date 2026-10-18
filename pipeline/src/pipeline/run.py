"""Building dates end to end, and the backfill / daily catch-up loop."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import xarray as xr

from .derived import compute_layers
from .fetch import PRESSURE_DAILY, SINGLE_DAILY, build_requests, fetch_dates
from .publish import encode_date, publish_date
from .tidy import build_tidy, write_tidy
from .validate import check, global_means, write_log

RAW_KEEP_DAYS = 30  # spec: keep native files for 30 days
TIDY_KEEP_DAYS = 90  # the map's window; tidy files feed later point/series builds


def _tidy_path(work: Path, day: date) -> Path:
    return work / f"tidy_{day.isoformat()}.nc"


def build_date(day: date, raw: Path, work: Path, out: Path) -> list[str]:
    """Tidy (if needed), derive, encode, validate and publish one date.

    Returns the validation problems; a date with problems is logged but not published.
    """
    path = _tidy_path(work, day)
    if path.is_file():
        tidy = xr.load_dataset(path)
    else:
        tidy = build_tidy(day, raw)
        write_tidy(tidy, work)
    layers = compute_layers(tidy)
    files, stats = encode_date(layers)
    problems = check(tidy, layers, stats)
    write_log(out, day.isoformat(), global_means(tidy), problems)
    if not problems:
        publish_date(out, day.isoformat(), files)
    return problems


def latest_available(c) -> date:
    """The newest date both daily-statistics datasets have."""
    return min(c.get_collection(cid).end_datetime.date() for cid in (SINGLE_DAILY, PRESSURE_DAILY))


def target_dates(latest: date, days: int) -> list[date]:
    return [latest - timedelta(days=k) for k in range(days - 1, -1, -1)]


_RAW = re.compile(r"^(single_mean|single_sum|pressure_mean)_(\d{4}-\d{2}-\d{2})\.nc$")
_TIDY = re.compile(r"^tidy_(\d{4}-\d{2}-\d{2})\.nc$")


def prune(raw: Path, work: Path, newest: date, raw_days=RAW_KEEP_DAYS, tidy_days=TIDY_KEEP_DAYS):
    """Delete per-date raw archives and tidy files older than their windows.

    A raw archive goes only once its date has a tidy file: a date whose other archives are
    still queued keeps the ones it has, or they would be requested again.
    """
    for folder, pattern, keep in ((raw, _RAW, raw_days), (work, _TIDY, tidy_days)):
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            m = pattern.match(p.name)
            if not m:
                continue
            day = date.fromisoformat(m.groups()[-1])
            if (newest - day).days < keep:
                continue
            if folder is raw and not _tidy_path(work, day).is_file():
                continue
            p.unlink()


def _published(out: Path) -> set[str]:
    path = out / "manifest.json"
    return set(json.loads(path.read_text())["dates"]) if path.is_file() else set()


def _ready(day: date, raw: Path, work: Path) -> bool:
    if _tidy_path(work, day).is_file():
        return True
    return all((raw / s.filename).is_file() for s in build_requests(day))


@dataclass
class BackfillResult:
    built: list[date] = field(default_factory=list)
    failed: dict[date, list[str]] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)


def backfill(
    c,
    latest: date,
    days: int,
    raw: Path,
    work: Path,
    out: Path,
    wait: bool = False,
    fetch: Callable = fetch_dates,
    build: Callable = build_date,
    log: Callable[[str], None] = lambda _msg: None,
    sleep: Callable[[float], None] = time.sleep,
) -> BackfillResult:
    """Make sure the last `days` dates up to `latest` are published.

    Each pass collects and queues CDS requests (without blocking), builds every date whose
    archives are all there, and prunes old files. With `wait`, passes repeat with backoff
    until nothing is pending. Dates that fail validation are not retried in the same run.
    """
    result = BackfillResult()
    targets = target_dates(latest, days)
    delay = 60.0
    while True:
        published = _published(out)
        todo = [d for d in targets if d.isoformat() not in published and d not in result.failed]
        result.pending = fetch(c, todo, raw) if todo else []
        for d in todo:
            if not _ready(d, raw, work):
                continue
            problems = build(d, raw, work, out)
            if problems:
                result.failed[d] = problems
                log(f"{d}: not published: {'; '.join(problems)}")
            else:
                result.built.append(d)
                log(f"{d}: published")
        prune(raw, work, latest)
        if not wait or not result.pending:
            return result
        log(f"waiting on {len(result.pending)} CDS request(s); next check in {delay:.0f} s")
        sleep(delay)
        delay = min(delay * 1.5, 600.0)
