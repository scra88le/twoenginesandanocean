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


def synthetic_tidy(**overrides):
    """A tidy 0.5 degree dataset with constant fields; the southern hemisphere is ocean."""
    from pipeline import derived as d

    lat = 89.75 - 0.5 * np.arange(360)
    lon = -179.75 + 0.5 * np.arange(720)
    base = {
        "tsr": 300.0, "olr": d.SIGMA * 255.0**4, "ssr": 200.0, "skt": 300.0,
        "le": 60.0, "h": 20.0, "bld": 2.0, "tcwv": 25.0, "tp": 3.0 / 86_400,
        "u10": 3.0, "v10": 4.0, "u100": 6.0, "v100": 8.0, "u250": 30.0, "v250": 40.0,
        "p59.162": 2.0e6, "p86.162": 0.0, "lsm": 1.0,
    }  # fmt: skip
    base.update(overrides)
    dims = ("latitude", "longitude")
    fields = {k: (dims, np.full((360, 720), float(v))) for k, v in base.items()}
    fields["lsm"][1][180:] = 0.0
    coords = {"latitude": lat, "longitude": lon}
    return xr.Dataset(fields, coords=coords, attrs={"date": "2026-10-01"})
