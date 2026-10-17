"""Fetch ERA5 daily statistics from the Climate Data Store.

Requests are built by pure functions and submitted without blocking: the CDS queue can take
hours, so a run stores request IDs and collects finished results later.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

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
        _v("p75.162", "vertical_integral_of_eastward_total_energy_flux"),
        _v("p76.162", "vertical_integral_of_northward_total_energy_flux"),
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


def _common(day: date) -> dict[str, Any]:
    if not isinstance(day, date):
        raise TypeError(f"expected datetime.date, got {type(day).__name__}")
    return {
        "product_type": "reanalysis",
        "year": f"{day.year:04d}",
        "month": f"{day.month:02d}",
        "day": f"{day.day:02d}",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
    }


def _single(day: date, statistic: str) -> dict[str, Any]:
    names = [
        v.cds_name
        for v in VARIABLES.values()
        if v.collection == SINGLE_DAILY and v.statistic == statistic
    ]
    return {**_common(day), "variable": names, "daily_statistic": f"daily_{statistic}"}


def build_requests(day: date) -> list[FetchSpec]:
    """The three CDS requests needed for one date.

    The spec asked for one request per dataset per date, but a daily-statistics request has a
    single `daily_statistic`, so the single-levels dataset needs one request for means and one
    for sums.
    """
    pressure = {
        **_common(day),
        "variable": [v.cds_name for v in VARIABLES.values() if v.collection == PRESSURE_DAILY],
        "pressure_level": ["250"],
        "daily_statistic": "daily_mean",
    }
    stamp = day.isoformat()
    return [
        FetchSpec("single_mean", SINGLE_DAILY, _single(day, "mean"), f"single_mean_{stamp}.nc"),
        FetchSpec("single_sum", SINGLE_DAILY, _single(day, "sum"), f"single_sum_{stamp}.nc"),
        FetchSpec("pressure_mean", PRESSURE_DAILY, pressure, f"pressure_mean_{stamp}.nc"),
    ]


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
