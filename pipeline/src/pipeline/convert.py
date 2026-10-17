"""Unit conversion, sign flips and regridding of raw ERA5 daily statistics.

This is the only module that flips signs. ERA5 fluxes are positive downwards; the converted
fields are positive upwards and renamed so a flipped field can't be mistaken for a raw one.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import xarray as xr

SECONDS_PER_DAY = 86_400

# Raw name -> converted name, for fluxes whose sign is flipped.
FLIPPED = {"ttr": "olr", "slhf": "le", "sshf": "h", "str": "lw_up"}
# Raw accumulated energy fields (J m-2 per day, from daily_sum) -> W m-2.
ENERGY_ACCUMULATED = ("tsr", "ttr", "ssr", "slhf", "sshf", "str", "bld")
CONVERTED_NAMES = frozenset(FLIPPED.values())


def accumulated_to_flux(joules_per_m2_per_day):
    """J m-2 accumulated over a day -> W m-2."""
    return joules_per_m2_per_day / SECONDS_PER_DAY


def precip_to_kg_m2_s(metres_per_day):
    """Precipitation in m of water per day -> kg m-2 s-1."""
    return metres_per_day * 1000.0 / SECONDS_PER_DAY


def precip_mm_per_day(metres_per_day):
    return metres_per_day * 1000.0


def convert_fields(raw: Mapping[str, xr.DataArray]) -> xr.Dataset:
    """Raw ERA5 daily fields (by ERA5 short name) -> converted, sign-flipped fields."""
    out: dict[str, xr.DataArray] = {}
    for name, da in raw.items():
        if name in CONVERTED_NAMES:
            raise ValueError(f"{name!r} is already converted; convert_fields takes raw ERA5 names")
        if name in ENERGY_ACCUMULATED:
            flux = accumulated_to_flux(da)
            if name in FLIPPED:
                out[FLIPPED[name]] = flux.copy(data=-flux.values).assign_attrs(
                    units="W m-2", sign="positive upward", era5_name=name
                )
            else:
                out[name] = flux.assign_attrs(units="W m-2", sign="positive downward")
        elif name == "tp":
            out[name] = precip_to_kg_m2_s(da).assign_attrs(units="kg m-2 s-1")
        else:
            out[name] = da.copy()
    return xr.Dataset(out)


def to_lon_180(da: xr.DataArray) -> xr.DataArray:
    """Roll longitude from 0..359.75 to -180..179.75."""
    wrapped = ((da["longitude"] + 180) % 360) - 180
    return da.assign_coords(longitude=wrapped).sortby("longitude")


def _lat_weights(n_fine: int = 721, n_coarse: int = 360) -> np.ndarray:
    """Area (sin-latitude) overlap of each 0.25-degree point cell with each 0.5-degree row."""
    centres = 90.0 - 0.25 * np.arange(n_fine)
    lo = np.clip(centres - 0.125, -90, 90)
    hi = np.clip(centres + 0.125, -90, 90)
    c_hi = 90.0 - 0.5 * np.arange(n_coarse)
    c_lo = c_hi - 0.5
    top = np.minimum(hi[None, :], c_hi[:, None])
    bottom = np.maximum(lo[None, :], c_lo[:, None])
    return np.clip(np.sin(np.deg2rad(top)) - np.sin(np.deg2rad(bottom)), 0, None)


def _lon_weights(n_fine: int = 1440, n_coarse: int = 720) -> np.ndarray:
    """Width overlap of each 0.25-degree point cell with each 0.5-degree column, periodic."""
    centres = -180.0 + 0.25 * np.arange(n_fine)
    lo, hi = centres - 0.125, centres + 0.125
    c_lo = -180.0 + 0.5 * np.arange(n_coarse)
    c_hi = c_lo + 0.5
    w = np.zeros((n_coarse, n_fine))
    for shift in (-360.0, 0.0, 360.0):
        top = np.minimum(hi[None, :] + shift, c_hi[:, None])
        bottom = np.maximum(lo[None, :] + shift, c_lo[:, None])
        w += np.clip(top - bottom, 0, None)
    return w


def regrid_half_degree(da: xr.DataArray, min_coverage: float = 0.5) -> xr.DataArray:
    """Conservative remap of a (721, 1440) ERA5 field, lon -180..179.75, to 360 x 720.

    ERA5 points sit on a point-centred grid including both poles, so a 2x2 block average
    doesn't apply. Each point owns the 0.25-degree cell around it (pole points own a sliver),
    and each 0.5-degree cell takes the area-weighted mean of the overlapping point cells.
    Missing (NaN) points are left out of the mean; a cell with less than `min_coverage` of
    its area covered is NaN.
    """
    if da.shape != (721, 1440):
        raise ValueError(f"expected a (721, 1440) ERA5 field, got {da.shape}")
    w_lat, w_lon = _lat_weights(), _lon_weights()
    x = da.values.astype("float64")
    valid = np.isfinite(x)
    num = w_lat @ np.where(valid, x, 0.0) @ w_lon.T
    den = w_lat @ valid.astype("float64") @ w_lon.T
    full = w_lat.sum(axis=1)[:, None] * w_lon.sum(axis=1)[None, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den >= min_coverage * full, num / den, np.nan)
    return xr.DataArray(
        out,
        coords={
            "latitude": 89.75 - 0.5 * np.arange(360),
            "longitude": -179.75 + 0.5 * np.arange(720),
        },
        dims=("latitude", "longitude"),
        name=da.name,
        attrs=da.attrs,
    )
