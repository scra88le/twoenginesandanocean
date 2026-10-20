"""The daily job: collect and submit CDS requests, build any new dates, publish them.

It runs on a machine that is gone afterwards (a GitHub Actions runner), so everything it needs
comes from the object store and everything it produces goes back there. One run:

1. Check the CDS credentials, then ask which date is the newest available. This comes first, so
   bad credentials or a CDS outage fail the run before anything is downloaded or changed:
   yesterday's site stays as it is. (The credentials need their own check: CDS serves the
   collection metadata without a key, so a bad key would otherwise only fail at the first
   request, and not at all on a day with nothing to request.)
2. Download the state: manifest, validation log, in-flight request IDs, the climatology and the
   scalar maps of the published dates.
3. Run one backfill pass over the last `days` dates (never waiting on the queue): collect
   finished requests, submit missing ones, and build, validate and publish every date whose
   archives are all there, then rebuild the series.
4. Upload (manifest last, see `deploy.upload`) and save the request IDs.

A date that fails validation is skipped and logged and the other dates are still published; the
caller turns that into a failing exit code so the run shows red.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path

from .deploy import UploadResult, download_state, upload, upload_state
from .fetch import fetch_dates, settle_state
from .points import build_series
from .run import _published, backfill, build_date, latest_available
from .store import Store


@dataclass
class DailyResult:
    latest: date
    built: list[date] = field(default_factory=list)
    failed: dict[date, list[str]] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)
    uploaded: UploadResult | None = None


def run_daily(
    store: Store,
    c,
    raw: Path,
    work: Path,
    out: Path,
    days: int = 10,
    log: Callable[[str], None] = lambda _m: None,
    fetch: Callable | None = None,
    build: Callable = build_date,
    series: Callable[[Path], int] = build_series,
) -> DailyResult:
    c.check_authentication()
    latest = latest_available(c)
    log(f"latest ERA5 daily date: {latest}")
    download_state(store, raw, out, log)
    try:
        passes = backfill(
            c, latest, days, raw, work, out, wait=False,
            fetch=fetch or partial(fetch_dates, keep_collected=True),
            build=build, log=log, series=series,
        )  # fmt: skip
        settle_state(raw, _published(out), latest)
    except BaseException:
        upload_state(store, raw)  # keep the requests submitted before the failure
        raise
    result = DailyResult(latest, passes.built, passes.failed, passes.pending)
    if (out / "manifest.json").is_file() and (passes.built or passes.failed):
        result.uploaded = upload(store, out, log)  # failed dates changed the log too
    upload_state(store, raw)
    return result
