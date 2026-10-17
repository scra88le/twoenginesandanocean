"""Synthetic CDS archives shaped like the real ones (721 x 1440, valid_time, optional level)."""

import zipfile

import numpy as np
import xarray as xr

LAT = np.linspace(90, -90, 721)
LON = np.arange(0, 360, 0.25)


def write_member(path, var, value, pressure=False):
    dims = ("valid_time", "latitude", "longitude")
    shape = (1, 721, 1440)
    coords = {
        "valid_time": np.array(["2026-10-01"], dtype="datetime64[ns]"),
        "latitude": LAT,
        "longitude": LON,
        "number": 0,
    }
    if pressure:
        dims = ("valid_time", "pressure_level", "latitude", "longitude")
        shape = (1, 1, 721, 1440)
        coords["pressure_level"] = np.array([250.0])
    da = xr.DataArray(np.full(shape, value, dtype="float32"), dims=dims, coords=coords)
    da.to_dataset(name=var).to_netcdf(path)


def make_archive(zpath, members, workdir):
    """members: {member filename: (netcdf variable, value, has_pressure_level)}"""
    with zipfile.ZipFile(zpath, "w") as z:
        for name, (var, val, pl) in members.items():
            p = workdir / name
            write_member(p, var, val, pl)
            z.write(p, name)
    return zpath
