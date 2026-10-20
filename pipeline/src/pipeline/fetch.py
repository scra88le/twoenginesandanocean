"""Fetch ERA5 daily statistics from the Climate Data Store.

Requests are built by pure functions and submitted without blocking: the CDS queue can take
hours, so a run stores request IDs and collects finished results later.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

SINGLE_DAILY = "derived-era5-single-levels-daily-statistics"
PRESSURE_DAILY = "derived-era5-pressure-levels-daily-statistics"


@dataclass(frozen=True)
class Variable:
    key: str
    cds_name: str
    collection: str
    statistic: str  # "mean" for state variables, "sum" for accumulated ones


def _v(key: str, cds_name: str, statistic: str = "mean", collection: str = SINGLE_DAILY):
    return key, Variable(key, cds_name, collection, statistic)


# Keys are ERA5 short names, except the vertical integrals, which use the parameter IDs the
# spec refers to. The key -> CDS name mapping for those is confirmed against real files.
VARIABLES: dict[str, Variable] = dict(
    [
        _v("skt", "skin_temperature"),
        _v("u10", "10m_u_component_of_wind"),
        _v("v10", "10m_v_component_of_wind"),
        _v("u100", "100m_u_component_of_wind"),
        _v("v100", "100m_v_component_of_wind"),
        _v("tcwv", "total_column_water_vapour"),
        _v("lsm", "land_sea_mask"),
        _v("p59.162", "vertical_integral_of_kinetic_energy"),
        _v("p86.162", "vertical_integral_of_divergence_of_total_energy_flux"),
        _v("tsr", "top_net_solar_radiation", "sum"),
        _v("ttr", "top_net_thermal_radiation", "sum"),
        _v("ssr", "surface_net_solar_radiation", "sum"),
        _v("slhf", "surface_latent_heat_flux", "sum"),
        _v("sshf", "surface_sensible_heat_flux", "sum"),
        _v("bld", "boundary_layer_dissipation", "sum"),
        _v("tp", "total_precipitation", "sum"),
        _v("u250", "u_component_of_wind", collection=PRESSURE_DAILY),
        _v("v250", "v_component_of_wind", collection=PRESSURE_DAILY),
    ]
)

ACCUMULATED = tuple(k for k, v in VARIABLES.items() if v.statistic == "sum")


@dataclass(frozen=True)
class FetchSpec:
    name: str
    collection_id: str
    request: dict[str, Any]
    filename: str


def _check_date(day) -> date:
    if not isinstance(day, date):
        raise TypeError(f"expected datetime.date, got {type(day).__name__}")
    return day


def _specs(first: date, day_value, stamp: str) -> list[FetchSpec]:
    """The three requests (single-levels means and sums, pressure-level means) for a month's
    `day_value` (one "DD" or a list of them). A daily-statistics request carries a single
    `daily_statistic`, so the single-levels dataset needs two requests."""
    base = {
        "product_type": "reanalysis",
        "year": f"{first.year:04d}",
        "month": f"{first.month:02d}",
        "day": day_value,
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
    }

    def names(collection: str, statistic: str) -> list[str]:
        return [
            v.cds_name
            for v in VARIABLES.values()
            if v.collection == collection and v.statistic == statistic
        ]

    single = {"daily_statistic": "daily_mean", "variable": names(SINGLE_DAILY, "mean")}
    sums = {"daily_statistic": "daily_sum", "variable": names(SINGLE_DAILY, "sum")}
    pressure = {
        "daily_statistic": "daily_mean",
        "variable": names(PRESSURE_DAILY, "mean"),
        "pressure_level": ["250"],
    }
    return [
        FetchSpec("single_mean", SINGLE_DAILY, {**base, **single}, f"single_mean_{stamp}.nc"),
        FetchSpec("single_sum", SINGLE_DAILY, {**base, **sums}, f"single_sum_{stamp}.nc"),
        FetchSpec(
            "pressure_mean", PRESSURE_DAILY, {**base, **pressure}, f"pressure_mean_{stamp}.nc"
        ),
    ]


def build_requests(day: date) -> list[FetchSpec]:
    """The three requests for one date; their filenames are the per-date raw archives."""
    day = _check_date(day)
    return _specs(day, f"{day.day:02d}", day.isoformat())


def chunk_dates(days) -> list[list[date]]:
    """Split dates into runs of consecutive days within one month (one request each)."""
    chunks: list[list[date]] = []
    for d in sorted(set(map(_check_date, days))):
        last = chunks[-1][-1] if chunks else None
        if last and (d - last).days == 1 and d.month == last.month and d.year == last.year:
            chunks[-1].append(d)
        else:
            chunks.append([d])
    return chunks


def build_chunk_requests(chunk: list[date]) -> list[FetchSpec]:
    """The three requests for consecutive days within one month.

    Requesting a month at a time cuts a 90-day backfill from 270 requests to about 12. The CDS
    limit is 400 cost units per request, where cost = variables x days (9 x 31 at most here).
    """
    first, last = chunk[0], chunk[-1]
    if (first.year, first.month) != (last.year, last.month):
        raise ValueError("a chunk must lie within one month")
    return _specs(first, [f"{d.day:02d}" for d in chunk], f"{first}_{last}")


def read_credentials(
    env: Mapping[str, str] | None = None, rc_path: Path | None = None
) -> tuple[str, str]:
    """CDS (url, key) from CDSAPI_URL / CDSAPI_KEY, else from ~/.cdsapirc."""
    env = os.environ if env is None else env
    if env.get("CDSAPI_URL") and env.get("CDSAPI_KEY"):
        return env["CDSAPI_URL"], env["CDSAPI_KEY"]
    rc_path = Path.home() / ".cdsapirc" if rc_path is None else rc_path
    if rc_path.is_file():
        pairs = (line.split(":", 1) for line in rc_path.read_text().splitlines() if ":" in line)
        found = {k.strip(): v.strip() for k, v in pairs}
        if found.get("url") and found.get("key"):
            return found["url"], found["key"]
    raise RuntimeError("No CDS credentials: set CDSAPI_URL and CDSAPI_KEY, or create ~/.cdsapirc")


def client():
    """An authenticated CDS client."""
    from ecmwf.datastores import Client

    url, key = read_credentials()
    return Client(url=url, key=key, progress=False)


_FAILED = {"failed", "rejected", "dismissed"}
_COLLECTION = {
    "single_mean": SINGLE_DAILY,
    "single_sum": SINGLE_DAILY,
    "pressure_mean": PRESSURE_DAILY,
}

# The CDS rejects requests beyond a (variable, undocumented) number queued per dataset per
# user: 8 at once on the single-levels dataset were mostly rejected on 2026-10-18.
MAX_QUEUED = 2


def _load_state(path: Path) -> dict[str, dict]:
    """Queued requests: {chunk filename: {"id", "name", "days"}}. Older entries are dropped."""
    state = json.loads(path.read_text()) if path.is_file() else {}
    return {k: v for k, v in state.items() if isinstance(v, dict) and "id" in v}


def _save_state(path: Path, state: dict[str, dict]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(tmp, path)


def split_archive(src: Path, name: str, raw_dir: Path) -> list[Path]:
    """Split a multi-day CDS archive into per-date archives `{name}_{date}.nc`.

    Each member NetCDF keeps its file name and a length-1 `valid_time`, so the per-date
    archives look exactly like single-day results. Existing per-date archives are kept.
    """
    import tempfile
    import zipfile

    import xarray as xr

    raw_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(src) as zf, tempfile.TemporaryDirectory() as tmp:
        members = []
        for info in zf.infolist():
            if info.filename.startswith("/") or ".." in info.filename or "/" in info.filename:
                raise ValueError(f"unsafe member name in archive: {info.filename!r}")
            if info.filename.endswith(".nc"):
                members.append((info.filename, xr.load_dataset(zf.extract(info, tmp))))
        times = sorted({t for _, ds in members for t in ds["valid_time"].values})
        for t in times:
            day = str(np.datetime_as_string(t, unit="D"))
            target = raw_dir / f"{name}_{day}.nc"
            if target.exists():
                continue
            part = target.with_name(target.name + ".part")
            with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as out:
                for member, ds in members:
                    one = Path(tmp) / f"day-{member}"
                    ds.sel(valid_time=[t]).to_netcdf(one)
                    out.write(one, member)
            os.replace(part, target)
            written.append(target)
    return written


def fetch_dates(
    c, days, raw_dir: Path, max_queued: int = MAX_QUEUED, keep_collected: bool = False
) -> list[str]:
    """Advance the downloads for some dates by one step, without waiting on the queue.

    First collects every queued request: a finished one is downloaded and split into
    per-date archives, a failed one is forgotten so its dates are requested again. Then dates
    still missing an archive, and not covered by a queued request, are submitted in runs of
    consecutive days within a month, oldest first and at most `max_queued` per dataset (the
    CDS rejects more). Queued requests (with the dates they cover) live in
    `raw_dir/pending.json`, so later runs pick up where this one left off. Returns the chunk
    names still pending.

    With `keep_collected`, a finished request stays in the state after it is collected, and a
    result that can no longer be downloaded (CDS keeps results only for a while) is forgotten
    so its dates are requested again. This is for a job whose `raw_dir` does not survive the
    run (the daily GitHub Action): the archives vanish with the machine, so the request must
    be collected again next time until its dates are published (see `settle_state`).
    """
    days = sorted(set(map(_check_date, days)))
    raw_dir.mkdir(parents=True, exist_ok=True)
    state_path = raw_dir / "pending.json"
    state = _load_state(state_path)

    for key, job in list(state.items()):
        st = c.get_remote(job["id"]).status
        if st == "successful":
            chunk = raw_dir / key
            part = chunk.with_name(chunk.name + ".part")
            try:
                c.get_remote(job["id"]).download(str(part))
            except Exception:
                if not keep_collected:
                    raise
                part.unlink(missing_ok=True)
                del state[key]  # expired at CDS: its dates are requested again below
                _save_state(state_path, state)
                continue
            os.replace(part, chunk)
            split_archive(chunk, job["name"], raw_dir)
            chunk.unlink()
            if not keep_collected:
                del state[key]
        elif st in _FAILED:
            del state[key]
        _save_state(state_path, state)

    missing = {}
    for name in _COLLECTION:
        covered = {d for job in state.values() if job["name"] == name for d in job["days"]}
        missing[name] = [
            d
            for d in days
            if not (raw_dir / f"{name}_{d}.nc").exists() and d.isoformat() not in covered
        ]
    # Oldest chunks first across the three statistics, so whole dates complete in order.
    todo = sorted(
        (chunk[0], name, chunk) for name in _COLLECTION for chunk in chunk_dates(missing[name])
    )
    for _, name, chunk in todo:
        if sum(_COLLECTION[j["name"]] == _COLLECTION[name] for j in state.values()) >= max_queued:
            continue
        spec = next(s for s in build_chunk_requests(chunk) if s.name == name)
        state[spec.filename] = {
            "id": submit(c, spec),
            "name": name,
            "days": [d.isoformat() for d in chunk],
        }
        _save_state(state_path, state)
    _save_state(state_path, state)
    return sorted(state)


def fetch_date(c, day: date, raw_dir: Path) -> list[str]:
    """`fetch_dates` for a single date."""
    return fetch_dates(c, [day], raw_dir)


def submit(c, spec: FetchSpec) -> str:
    """Queue one request and return its ID without waiting."""
    return c.submit(spec.collection_id, spec.request).request_id


def status(c, request_id: str) -> str:
    return c.get_remote(request_id).status


def download(c, request_id: str, target: Path) -> Path:
    """Download a finished request to `target`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    c.get_remote(request_id).download(str(target))
    return target


def settle_state(raw_dir: Path, published: set[str], today: date, max_age_days: int = 30) -> int:
    """Forget requests whose dates are all published, or are too old to matter (a date that
    keeps failing validation must not keep its request forever). Returns how many were dropped.
    """
    state_path = raw_dir / "pending.json"
    state = _load_state(state_path)
    dropped = 0
    for key, job in list(state.items()):
        days = job["days"]
        stale = (today - date.fromisoformat(max(days))).days > max_age_days
        if stale or all(d in published for d in days):
            del state[key]
            dropped += 1
    if dropped:
        _save_state(state_path, state)
    return dropped
