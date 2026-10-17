"""Read the archives CDS returns into raw ERA5 fields keyed by the spec's names."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import xarray as xr

# NetCDF variable name -> key used throughout the pipeline. Everything else keeps its name.
# Confirmed against real files (GRIB param IDs 162059, 162086, 162075, 162076).
NC_TO_KEY = {
    "vike": "p59.162",
    "vited": "p86.162",
    "vitee": "p75.162",
    "viten": "p76.162",
    "u": "u250",
    "v": "v250",
}

_EXTRA_DIMS = ("valid_time", "pressure_level")


def load_raw_archive(path: Path) -> dict[str, xr.DataArray]:
    """Load every NetCDF in a CDS result archive as 2-D (latitude, longitude) float64 fields.

    CDS returns a zip holding one NetCDF per variable, whatever the file is named. Archives
    are untrusted downloads, so each member is checked and extracted into its own new
    temporary directory.
    """
    out: dict[str, xr.DataArray] = {}
    with zipfile.ZipFile(path) as zf, tempfile.TemporaryDirectory() as tmp:
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts or "/" in name:
                raise ValueError(f"unsafe member name in archive: {name!r}")
            if not name.endswith(".nc"):
                continue
            target = zf.extract(info, tmp)
            with xr.open_dataset(target) as ds:
                for var, da in ds.data_vars.items():
                    key = NC_TO_KEY.get(str(var), str(var))
                    if key in out:
                        raise ValueError(f"duplicate variable {key!r} in {path}")
                    out[key] = _squeeze(da).load()
    return out


def _squeeze(da: xr.DataArray) -> xr.DataArray:
    for dim in _EXTRA_DIMS:
        if dim in da.dims:
            da = da.isel({dim: 0})
    da = da.drop_vars([c for c in da.coords if c not in ("latitude", "longitude")])
    return da.astype("float64").transpose("latitude", "longitude")
