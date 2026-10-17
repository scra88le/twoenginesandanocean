"""Assemble one date's raw CDS archives into a tidy, converted 0.5 degree dataset."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import xarray as xr

from .convert import tidy_dataset
from .fetch import build_requests
from .load import load_raw_archive


def build_tidy(day: date, raw_dir: Path) -> xr.Dataset:
    specs = build_requests(day)
    missing = [s.name for s in specs if not (raw_dir / s.filename).is_file()]
    if missing:
        raise FileNotFoundError(f"missing raw archives for {day}: {', '.join(missing)}")
    raw: dict[str, xr.DataArray] = {}
    for spec in specs:
        for key, da in load_raw_archive(raw_dir / spec.filename).items():
            if key in raw:
                raise ValueError(f"variable {key!r} appears in more than one archive")
            raw[key] = da
    return tidy_dataset(raw, day.isoformat())


def write_tidy(ds: xr.Dataset, work_dir: Path) -> Path:
    """Write `tidy_{date}.nc` (float32, compressed) via a partial file, so it is never torn."""
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"tidy_{ds.attrs['date']}.nc"
    part = target.with_name(target.name + ".part")
    encoding = {k: {"zlib": True, "complevel": 4, "dtype": "float32"} for k in ds.data_vars}
    ds.to_netcdf(part, encoding=encoding)
    os.replace(part, target)
    return target
