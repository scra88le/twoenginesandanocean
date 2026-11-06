"""The technosphere's annual grids: national primary power placed where its heat is released.

Kleidon's free-energy cascade for humanity (`pipeline.derived`, "the technosphere"): each
country's direct-equivalent primary power, by source, is split into components (conversion
losses at power stations, delivered electricity, fuel burnt at the point of use) and each
component is spread over the country's cells with a spatial proxy:

| Component | Placed by |
| --- | --- |
| `losses_fossil` | EDGAR power-industry CO2 (power stations) |
| `losses_nuclear` | WRI Global Power Plant Database, nuclear capacity |
| `losses_renewable` | WRI database, biomass, waste and geothermal capacity |
| `elec_industry`, `fuel_industry` | EDGAR industrial combustion and fuel exploitation CO2 |
| `elec_buildings`, `fuel_buildings` | EDGAR buildings CO2 |
| `fuel_transport` | EDGAR transport CO2 over land |
| `fuel_bunkers` | EDGAR transport CO2 over the open ocean (no country), worldwide |

A component whose proxy is empty in a country falls back to the next proxy in its chain and
finally to the country's land area, and the report lists every fallback. National totals are
conserved exactly; countries with no cells on the grid are reported as unplaced.

Inputs (all free): Our World in Data's energy dataset (Energy Institute and Ember, CC BY),
Natural Earth admin-0 countries (public domain), the WRI Global Power Plant Database (CC BY
4.0) and EDGAR's CO2 sector gridmaps (JRC, CC BY 4.0). Everything here is annual; the daily
shaping comes in a later milestone.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import xarray as xr

from . import derived as d

NLAT, NLON = d.NLAT, d.NLON
FINE = 5  # rasterise countries at 0.1 degree: 5 x 5 sub-cells per 0.5 degree cell

# Inputs hosted on GitHub (reachable from Actions and most sandboxes).
URLS = {
    "owid-energy-data.csv": "https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv",
    "ne_50m_admin_0_countries.geojson": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson",
    "global_power_plant_database.csv": "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv",
}  # fmt: skip
EDGAR_URL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/EDGAR/datasets/{release}/monthly/CO2/"
    "bkl_{sector}/bkl_{sector}_emi_nc.zip"
)
EDGAR_RELEASE = "EDGAR_2024_GHG"
# EDGAR's aggregated ("bkl") sectors, and the older detailed codes, mapped to our proxies.
EDGAR_SECTORS = {
    "POWER_INDUSTRY": "power", "ENE": "power",
    "IND_COMBUSTION": "industry", "IND": "industry",
    "FUEL_EXPLOITATION": "industry", "REF_TRF": "industry",
    "TRANSPORT": "transport", "TRO": "transport", "TNR": "transport",
    "BUILDINGS": "buildings", "RCO": "buildings",
}  # fmt: skip
EDGAR_DOWNLOAD = ("POWER_INDUSTRY", "IND_COMBUSTION", "FUEL_EXPLOITATION", "TRANSPORT", "BUILDINGS")
# The years whose months make the typical seasonal shape: recent, without the COVID years.
FACTOR_YEARS = (2016, 2017, 2018, 2019, 2022, 2023)
# The sector code a reduced file is named with, so `_edgar_sector` reads it back.
REDUCED_SECTOR = {"power": "POWER_INDUSTRY", "industry": "IND_COMBUSTION",
                  "transport": "TRANSPORT", "buildings": "BUILDINGS"}  # fmt: skip
EDGAR_YEARS = FACTOR_YEARS  # the newest of them also places the components

# Each component's seasonal shape: its sector's monthly factor in its country. Nuclear and
# bioenergy/geothermal stations run near flat all year (None: factor 1). Electricity follows
# the power sector, and the bunkers follow transport over the open ocean, worldwide.
COMPONENT_SECTOR = {
    "losses_fossil": "power", "losses_nuclear": None, "losses_renewable": None,
    "elec_industry": "power", "elec_buildings": "power",
    "fuel_industry": "industry", "fuel_transport": "transport", "fuel_buildings": "buildings",
    "fuel_bunkers": "transport",
}  # fmt: skip
# The components a day's weather scales (heating and cooling).
BUILDINGS = ("elec_buildings", "fuel_buildings")
FRAMES = ("p_base", "p_bldg", "w_base", "w_bldg")  # P and useful work, without and with weather

# OWID columns: primary energy for the fuels, electricity generated for the rest (TWh).
OWID_COLUMNS = {
    "coal": "coal_consumption", "oil": "oil_consumption", "gas": "gas_consumption",
    "biofuel": "biofuel_consumption", "nuclear": "nuclear_electricity",
    "hydro": "hydro_electricity", "wind": "wind_electricity", "solar": "solar_electricity",
    "other_renewable": "other_renewable_electricity",
}  # fmt: skip
OWID_ALIASES = {"OWID_KOS": "KOS"}  # OWID's code -> Natural Earth's

# Used only when EDGAR is missing (a smoke run): world-average shares of fossil fuel.
DEFAULT_SHARES = {"power": 0.40, "industry": 0.25, "transport": 0.25, "buildings": 0.10}
DEFAULT_BUNKER_SHARE_OF_OIL = 0.08  # international aviation and shipping, about 8 % of oil

# Where each component's heat is released: a chain of proxies, then land area.
PLACEMENT = {
    "losses_fossil": ("power", "fossil_plants"),
    "losses_nuclear": ("nuclear_plants", "power"),
    "losses_renewable": ("renewable_plants", "power"),
    "elec_industry": ("industry", "buildings"),
    "elec_buildings": ("buildings", "industry"),
    "fuel_industry": ("industry",),
    "fuel_transport": ("transport",),
    "fuel_buildings": ("buildings",),
}
GPPD_FUELS = {
    "Nuclear": "nuclear_plants",
    "Biomass": "renewable_plants", "Waste": "renewable_plants", "Geothermal": "renewable_plants",
    "Coal": "fossil_plants", "Gas": "fossil_plants", "Oil": "fossil_plants",
    "Petcoke": "fossil_plants", "Cogeneration": "fossil_plants",
}  # fmt: skip

_AREA_ROW = d.cell_areas()[:, 0]  # m2, per 0.5 degree row


# ---- downloads -------------------------------------------------------------------------


def _download(url: str, dest: Path, opener: Callable = urllib.request.urlopen) -> Path:
    """Stream `url` to `dest` (EDGAR's monthly zips are gigabytes: never held in memory)."""
    tmp = dest.with_name(dest.name + ".part")
    try:
        with opener(url, timeout=300) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)
    return dest


def fetch_inputs(
    folder: Path,
    edgar: bool = True,
    years: tuple[int, ...] | None = None,
    opener: Callable = urllib.request.urlopen,
):
    """Download the inputs into `folder` (existing files are kept). Each EDGAR zip is
    streamed to disk, its NetCDF files for `years` (default `EDGAR_YEARS`; None in a test
    keeps all) extracted into `folder/edgar/{sector}/`, and the zip deleted. Returns the
    paths written."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, url in URLS.items():
        if not (folder / name).is_file():
            written.append(_download(url, folder / name, opener))
    if edgar:
        for sector in EDGAR_DOWNLOAD:
            target = folder / "edgar" / sector
            if target.is_dir() and any(target.rglob("*.nc")):
                continue
            target.mkdir(parents=True, exist_ok=True)
            zpath = folder / "edgar" / f"{sector}.zip"
            try:
                _download(EDGAR_URL.format(release=EDGAR_RELEASE, sector=sector), zpath, opener)
                extracted = _extract_nc(zpath, target, EDGAR_YEARS if years is None else years)
            finally:
                zpath.unlink(missing_ok=True)
            written += reduce_edgar(target, extracted)
    return written


def reduce_edgar(folder: Path, files: list[Path]) -> list[Path]:
    """Sum EDGAR's 0.1 degree files into one 0.5 degree file per proxy and year (12 months on
    a time axis, or the year when the files have no months), and delete the originals: six
    years of five sectors at 0.1 degree would fill a runner's disk, at 0.5 degree they are
    about 12 MB a year. `load_edgar` reads the reduced files like any others."""
    by_key: dict[tuple[int, str], list[Path]] = {}
    for p in files:
        sector = _edgar_sector(p)
        years = [int(y) for y in _YEAR.findall(p.name)]
        if sector and years:
            by_key.setdefault((years[-1], sector), []).append(p)
    out = []
    lat = 89.75 - 0.5 * np.arange(NLAT)
    lon = -179.75 + 0.5 * np.arange(NLON)
    for (year, sector), paths in sorted(by_key.items()):
        months: dict[int, np.ndarray] = {}
        for p in paths:
            for m, f in _edgar_months(p).items():
                months[m] = months.get(m, 0) + f
        if all(m in months for m in range(1, 13)):
            data = np.stack([months[m] for m in range(1, 13)]).astype("float32")
            dims, coords = (
                ("time", "lat", "lon"),
                {"time": np.arange(1, 13), "lat": lat, "lon": lon},
            )
        else:
            data = sum(months.values()).astype("float32")
            dims, coords = ("lat", "lon"), {"lat": lat, "lon": lon}
        path = folder / f"EDGAR_reduced_CO2_{year}_{REDUCED_SECTOR[sector]}_0p5.nc"
        da = xr.DataArray(data, dims=dims, coords=coords, attrs={"units": "Tonnes per cell"})
        tmp = path.with_suffix(".nc.tmp")
        da.to_dataset(name="emissions").to_netcdf(tmp, encoding={"emissions": {"zlib": True}})
        tmp.replace(path)
        out.append(path)
        for p in paths:
            if p != path:
                p.unlink(missing_ok=True)
    return out


def _extract_nc(zpath: Path, target: Path, years: tuple[int, ...] | None = None) -> list[Path]:
    """Extract the NetCDF files of an untrusted zip whose names carry one of `years` (all of
    them if `years` is empty), flattened into `target` and streamed, never in memory."""
    target.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if info.is_dir() or not name.endswith(".nc") or name.startswith("."):
                continue
            if years and not {int(y) for y in _YEAR.findall(name)} & set(years):
                continue
            path = target / name
            with z.open(info) as src, path.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            out.append(path)
    return out


# ---- national energy -------------------------------------------------------------------


@dataclass
class NationalEnergy:
    year: int
    twh: dict[str, dict[str, float]]  # ISO3 -> source -> TWh per year
    world_twh: dict[str, float]
    estimated: list[str] = field(default_factory=list)  # fossil fuel estimated, not reported


def _num(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


def latest_full_year(rows: list[dict]) -> int:
    """The newest year the World row has every fuel for."""
    years = [
        int(r["year"])
        for r in rows
        if r["country"] == "World" and all(_num(r[OWID_COLUMNS[s]]) for s in d.FUEL_SOURCES)
    ]
    if not years:
        raise ValueError("no year has the World's fuel totals")
    return max(years)


def read_owid(path: Path, year: int | None = None) -> NationalEnergy:
    """National energy by source for one year (TWh per year), from OWID's energy CSV.

    The Energy Institute reports fuels for about 80 countries; the rest of the world's fuel
    (World minus those countries, per fuel) is shared among the other countries in
    proportion to their latest primary energy (EIA, within ten years), or their population,
    so the world's totals by fuel are kept exactly. Electricity by source (Ember) covers
    almost every country and is used as reported."""
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    year = year or latest_full_year(rows)
    world = next((r for r in rows if r["country"] == "World" and int(r["year"]) == year), None)
    if world is None:
        raise ValueError(f"no World row for {year}")
    world_twh = {s: _num(world[c]) or 0.0 for s, c in OWID_COLUMNS.items()}

    def code(r: dict) -> str | None:
        c = OWID_ALIASES.get(r["iso_code"], r["iso_code"])
        return c if c and not c.startswith("OWID") else None

    this_year = {code(r): r for r in rows if code(r) and int(r["year"]) == year}
    reported = {c for c, r in this_year.items() if _num(r["coal_consumption"]) is not None}

    twh: dict[str, dict[str, float]] = {}
    for c, r in this_year.items():
        twh[c] = {s: _num(r[col]) or 0.0 for s, col in OWID_COLUMNS.items()}
        if c not in reported:
            for s in d.FUEL_SOURCES:
                twh[c][s] = 0.0

    # Weights for sharing the rest of the world's fuel: latest primary energy, else population.
    def weight(c: str) -> float:
        hist = [r for r in rows if code(r) == c and year - 10 <= int(r["year"]) <= year]
        for key in ("primary_energy_consumption", "population"):
            vals = [(int(r["year"]), _num(r[key])) for r in hist if _num(r[key])]
            if vals:
                return max(vals)[1] * (1.0 if key.startswith("primary") else 1e-6)
        return 0.0

    rest = sorted(set(twh) - reported)
    weights = {c: weight(c) for c in rest}
    total_w = sum(weights.values())
    for s in d.FUEL_SOURCES:
        remainder = max(world_twh[s] - sum(twh[c][s] for c in reported), 0.0)
        for c in rest:
            twh[c][s] = remainder * weights[c] / total_w if total_w else 0.0
    return NationalEnergy(year, twh, world_twh, estimated=rest)


# ---- countries on the grid -------------------------------------------------------------


@dataclass
class CountryGrid:
    """Each country's land area in each 0.5 degree cell, as sparse triples."""

    codes: list[str]  # index -> ISO3
    cell: np.ndarray  # flat cell index (row * 720 + col)
    country: np.ndarray  # index into codes
    area: np.ndarray  # m2 of that country in that cell

    def land_share(self) -> np.ndarray:
        """Per triple: the country's share of the cell's land (sums to 1 per land cell)."""
        land = np.bincount(self.cell, weights=self.area, minlength=NLAT * NLON)
        return self.area / land[self.cell]

    def land_cells(self) -> np.ndarray:
        """Boolean (360, 720): cells with any land of any country."""
        out = np.zeros(NLAT * NLON, bool)
        out[self.cell] = True
        return out.reshape(NLAT, NLON)


def _feature_code(props: dict) -> str:
    for key in ("ISO_A3_EH", "ISO_A3", "ADM0_A3"):
        v = props.get(key)
        if v and v != "-99":
            return v
    return ""


def _rings(geometry: dict) -> list[tuple[list, list[list]]]:
    if geometry["type"] == "Polygon":
        return [(geometry["coordinates"][0], geometry["coordinates"][1:])]
    if geometry["type"] == "MultiPolygon":
        return [(p[0], p[1:]) for p in geometry["coordinates"]]
    return []


def _ring_area(ring) -> float:
    x, y = np.asarray(ring, dtype="float64").T
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def _fill(img: np.ndarray, rings: list[np.ndarray], value: int) -> None:
    """Even-odd scanline fill of one polygon (outer ring and holes, in pixel coordinates where
    pixel (i, j) spans [j, j+1) x [i, i+1)): a pixel is set when its centre is inside, so a
    polygon covers its true area with no outward bias along the coast."""
    edges = []
    for r in rings:
        r = r if np.array_equal(r[0], r[-1]) else np.vstack([r, r[:1]])
        edges.append(np.column_stack((r[:-1], r[1:])))
    e = np.vstack(edges)  # x0, y0, x1, y1
    e = e[e[:, 1] != e[:, 3]]  # horizontal edges never cross a scanline
    if e.size == 0:
        return
    x0, y0, x1, y1 = e.T
    top = max(int(np.floor(min(y0.min(), y1.min()))), 0)
    bottom = min(int(np.ceil(max(y0.max(), y1.max()))), img.shape[0])
    for i in range(top, bottom):
        yc = i + 0.5
        hit = (y0 <= yc) != (y1 <= yc)
        if not hit.any():
            continue
        xs = np.sort(x0[hit] + (yc - y0[hit]) * (x1[hit] - x0[hit]) / (y1[hit] - y0[hit]))
        for xa, xb in zip(xs[::2], xs[1::2], strict=False):
            j0 = max(int(np.ceil(xa - 0.5)), 0)
            j1 = min(int(np.ceil(xb - 0.5)), img.shape[1])
            if j1 > j0:
                img[i, j0:j1] = value


def country_grid(geojson: Path | dict) -> CountryGrid:
    """Rasterise country polygons at 0.1 degree and sum their area into 0.5 degree cells.
    Larger polygons are drawn first, so enclaves (Lesotho in South Africa) win their cells."""
    g = geojson if isinstance(geojson, dict) else json.loads(Path(geojson).read_text())
    codes: list[str] = []
    polys = []
    for feat in g["features"]:
        c = _feature_code(feat.get("properties") or {})
        if not c:
            continue
        if c not in codes:
            codes.append(c)
        for outer, holes in _rings(feat["geometry"]):
            polys.append((_ring_area(outer), codes.index(c) + 1, outer, holes))
    w, h = NLON * FINE, NLAT * FINE
    fine = np.zeros((h, w), dtype=np.int32)

    def px(ring):
        a = np.asarray([p[:2] for p in ring], dtype="float64")
        return np.column_stack(((a[:, 0] + 180.0) * FINE / 0.5, (90.0 - a[:, 1]) * FINE / 0.5))

    for _, idx, outer, holes in sorted(polys, key=lambda p: -p[0]):
        _fill(fine, [px(outer), *(px(r) for r in holes)], idx)

    rows, cols = np.nonzero(fine)
    idx = fine[rows, cols] - 1
    cell = (rows // FINE) * NLON + cols // FINE
    # Exact area of each fine pixel's row.
    edges = np.deg2rad(90.0 - (0.5 / FINE) * np.arange(h + 1))
    dlam = np.deg2rad(0.5 / FINE)
    fine_area = d.EARTH_RADIUS**2 * dlam * (np.sin(edges[:-1]) - np.sin(edges[1:]))
    key = cell.astype(np.int64) * len(codes) + idx
    uniq, inv = np.unique(key, return_inverse=True)
    area = np.bincount(inv, weights=fine_area[rows])
    return CountryGrid(codes, (uniq // len(codes)).astype(np.int64), uniq % len(codes), area)


# ---- spatial proxies -------------------------------------------------------------------


def to_half_degree(values: np.ndarray, lat: np.ndarray, lon: np.ndarray, per_area: bool):
    """Sum a finer regular lat-lon grid (cell-centred) into the 0.5 degree cells.
    `per_area` values (fluxes, per m2) are multiplied by their cell area first."""
    values = np.nan_to_num(np.asarray(values, dtype="float64"), nan=0.0)
    lat = np.asarray(lat, dtype="float64")
    lon = ((np.asarray(lon, dtype="float64") + 180.0) % 360.0) - 180.0
    if per_area:
        dlat = np.deg2rad(abs(float(lat[1] - lat[0])))
        dlon = np.deg2rad(abs(float(lon[1] - lon[0])))
        phi = np.deg2rad(lat)
        a = d.EARTH_RADIUS**2 * dlon * (np.sin(phi + dlat / 2) - np.sin(phi - dlat / 2))
        values = values * np.abs(a)[:, None]
    r = np.clip(((90.0 - lat) / 0.5).astype(int), 0, NLAT - 1)
    c = np.clip(((lon + 180.0) / 0.5).astype(int), 0, NLON - 1)
    flat = (r[:, None] * NLON + c[None, :]).ravel()
    return np.bincount(flat, weights=values.ravel(), minlength=NLAT * NLON).reshape(NLAT, NLON)


_YEAR = re.compile(r"(?<!\d)(19[7-9]\d|20[0-9]\d)(?!\d)")


def _edgar_sector(path: Path) -> str | None:
    text = str(path).upper()
    for code in sorted(EDGAR_SECTORS, key=len, reverse=True):
        if re.search(rf"(?<![A-Z]){code}(?![A-Z])", text):
            return EDGAR_SECTORS[code]
    return None


_MONTH = re.compile(r"(?<!\d)(?:19[7-9]\d|20\d\d)[_-](0?[1-9]|1[0-2])(?!\d)")


def _edgar_months(path: Path) -> dict[int, np.ndarray]:
    """One EDGAR file -> {month: (360, 720)} per 0.5 degree cell; month 0 is a whole year.
    A file holds either 12 months on a time axis, or one field whose month (if any) is in
    its name (`..._2023_1_...`): EDGAR doesn't document which, so both are read."""
    with xr.open_dataset(path) as ds:
        var = next(v for v in ds.data_vars.values() if v.ndim >= 2)
        lat = next(n for n in var.dims if n.lower().startswith("lat"))
        lon = next(n for n in var.dims if n.lower().startswith("lon"))
        other = [n for n in var.dims if n not in (lat, lon)]
        units = str(var.attrs.get("units", "")).replace(" ", "")
        per_area = "m-2" in units or "/m2" in units or "m^-2" in units

        def grid(a: xr.DataArray) -> np.ndarray:
            return to_half_degree(
                a.transpose(lat, lon).values, ds[lat].values, ds[lon].values, per_area
            )

        if len(other) == 1 and var.sizes[other[0]] == 12:
            return {m + 1: grid(var.isel({other[0]: m})) for m in range(12)}
        field = grid(var.sum(dim=other)) if other else grid(var)
        month = _MONTH.search(path.name)
        return {int(month.group(1)) if month else 0: field}


def _edgar_files(folder: Path) -> dict[int, list[tuple[str, Path]]]:
    """{year: [(proxy, path), ...]} for the EDGAR files in `folder` (searched recursively)."""
    found: dict[int, list[tuple[str, Path]]] = {}
    for p in sorted(folder.rglob("*.nc")) if folder.is_dir() else []:
        sector = _edgar_sector(p)
        years = [int(y) for y in _YEAR.findall(p.name)]
        if sector and years:
            found.setdefault(years[-1], []).append((sector, p))  # after the release name
    return found


def load_edgar(folder: Path, year: int) -> tuple[dict[str, np.ndarray], int | None]:
    """EDGAR CO2 sector gridmaps in `folder` -> {proxy: (360, 720)} summed per proxy over
    the year, for the latest year <= `year` that the files have. Returns the year used
    (None when there are no files)."""
    found = _edgar_files(folder)
    usable = [y for y in found if y <= year]
    if not usable:
        return {}, None
    used = max(usable)
    out: dict[str, np.ndarray] = {}
    for sector, p in found[used]:
        out[sector] = out.get(sector, 0) + sum(_edgar_months(p).values())
    return out, used


def load_edgar_monthly(
    folder: Path, years: tuple[int, ...] = FACTOR_YEARS
) -> tuple[dict[str, np.ndarray], list[int]]:
    """EDGAR's monthly sector gridmaps -> {proxy: (12, 360, 720)}, summed over the `years`
    that have all 12 months for every proxy they have (the typical seasonal shape; only the
    shape matters). Returns the years used."""
    found = _edgar_files(folder)
    out: dict[str, np.ndarray] = {}
    used = []
    for y in sorted(set(years) & set(found)):
        months: dict[str, dict[int, np.ndarray]] = {}
        for sector, p in found[y]:
            for m, f in _edgar_months(p).items():
                if m:
                    by = months.setdefault(sector, {})
                    by[m] = by.get(m, 0) + f
        complete = {s: v for s, v in months.items() if len(v) == 12}
        if not complete:
            continue
        used.append(y)
        for s, v in complete.items():
            out[s] = out.get(s, 0) + np.stack([v[m] for m in range(1, 13)])
    return out, used


def load_plants(path: Path) -> dict[str, np.ndarray]:
    """WRI Global Power Plant Database -> capacity (MW) per 0.5 degree cell, by kind."""
    out = {k: np.zeros((NLAT, NLON)) for k in set(GPPD_FUELS.values())}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            kind = GPPD_FUELS.get(r.get("primary_fuel", ""))
            try:
                lat, lon, mw = float(r["latitude"]), float(r["longitude"]), float(r["capacity_mw"])
            except (KeyError, ValueError):
                continue
            if kind is None or not (-90 <= lat <= 90) or mw <= 0:
                continue
            row = min(int((90.0 - lat) / 0.5), NLAT - 1)
            col = min(int(((lon + 180.0) % 360.0) / 0.5), NLON - 1)
            out[kind][row, col] += mw
    return out


# ---- allocation ------------------------------------------------------------------------


@dataclass
class Allocation:
    components: dict[str, np.ndarray]  # W m-2, (360, 720), annual means
    report: dict
    # W m-2, (12, 360, 720): each month's P and useful work, split into the buildings' part
    # (`*_bldg`, which a day's weather scales) and the rest (`*_base`); see `FRAMES`.
    frames: dict[str, np.ndarray] = field(default_factory=dict)


def allocate(
    energy: NationalEnergy,
    grid: CountryGrid,
    proxies: dict[str, np.ndarray],
    monthly: dict[str, np.ndarray] | None = None,
) -> Allocation:
    """Spread every country's components over its cells (see the module docstring), and
    each month's share of them: `monthly` is {proxy: (12, 360, 720)} sector emissions whose
    national sums give each country's monthly factors (flat without it)."""
    land = grid.land_cells()
    share = grid.land_share()
    # Direct-equivalent primary power by source, W (reactor and furnace heat, not electricity).
    watts = {
        c: {s: d.twh_per_year_to_watts(v) for s, v in d.direct_equivalent(src).items()}
        for c, src in energy.twh.items()
    }
    report: dict = {"year": energy.year, "fallbacks": {}, "default_shares": [], "unplaced_w": {}}

    # International bunkers: transport emissions over the open ocean, as a share of fossil.
    fossil_proxies = [proxies[k] for k in d.SECTORS if k in proxies]
    world_fossil = sum(sum(w.get(s, 0.0) for s in d.FOSSIL_SOURCES) for w in watts.values())
    world_oil = sum(w.get("oil", 0.0) for w in watts.values())
    if "transport" in proxies and fossil_proxies:
        sea = proxies["transport"][~land].sum()
        bunkers = world_fossil * sea / sum(p.sum() for p in fossil_proxies)
        report["bunker_basis"] = "EDGAR transport over the open ocean"
    else:
        bunkers = DEFAULT_BUNKER_SHARE_OF_OIL * world_oil
        report["bunker_basis"] = f"default, {DEFAULT_BUNKER_SHARE_OF_OIL:.0%} of oil"
    bunkers = min(bunkers, world_oil)
    kept, _ = d.remove_pro_rata({c: w.get("oil", 0.0) for c, w in watts.items()}, bunkers)
    for c, oil in kept.items():
        watts[c]["oil"] = oil

    out = {k: np.zeros(NLAT * NLON) for k in d.COMPONENTS}
    frames = {k: np.zeros((12, NLAT * NLON)) for k in FRAMES}
    by_code = {c: i for i, c in enumerate(grid.codes)}
    flat = {k: v.ravel() for k, v in proxies.items()}
    monthly_flat = {k: v.reshape(12, -1) for k, v in (monthly or {}).items()}
    report["monthly_basis"] = sorted(monthly_flat) if monthly_flat else "flat"

    def add_month(name: str, cells: np.ndarray, placed: np.ndarray, factors: np.ndarray):
        part = "bldg" if name in BUILDINGS else "base"
        f = factors[:, None] * placed[None, :]
        frames[f"p_{part}"][:, cells] += f
        frames[f"w_{part}"][:, cells] += d.USEFUL_FRACTION[name] * f

    def factors_for(sector: str | None, cells: np.ndarray, frac) -> np.ndarray:
        if sector is None or sector not in monthly_flat:
            return np.ones(12)
        return d.monthly_factors((monthly_flat[sector][:, cells] * frac).sum(axis=1))

    for code, w in sorted(watts.items()):
        if code not in by_code:
            report["unplaced_w"][code] = sum(w.values())
            continue
        sel = grid.country == by_code[code]
        cells, frac = grid.cell[sel], share[sel]
        sector_w = {
            s: float((flat[s][cells] * frac).sum()) if s in flat else 0.0 for s in d.SECTORS
        }
        total = sum(sector_w.values())
        if sum(w.get(s, 0.0) for s in d.FOSSIL_SOURCES) <= 0:
            shares = None  # no fossil fuel to split
        elif total > 0:
            shares = {s: v / total for s, v in sector_w.items()}
        else:
            shares = dict(DEFAULT_SHARES)
            report["default_shares"].append(code)
        comps = d.national_components(w, shares)
        for name, value in comps.items():
            if value <= 0:
                continue
            chosen, weights = None, grid.area[sel]  # last resort: the country's land area
            for proxy in PLACEMENT[name]:
                if proxy in flat and (flat[proxy][cells] * frac).sum() > 0:
                    chosen, weights = proxy, flat[proxy][cells] * frac
                    break
            if chosen != PLACEMENT[name][0]:
                report["fallbacks"].setdefault(name, []).append(code)
            placed = value * weights / weights.sum()
            out[name][cells] += placed  # a country's cells are distinct
            add_month(name, cells, placed, factors_for(COMPONENT_SECTOR[name], cells, frac))

    # Bunkers: worldwide, by transport emissions over the open ocean (or evenly by area).
    sea = ~land.ravel()
    if "transport" in proxies and proxies["transport"][~land].sum() > 0:
        bw = np.where(land, 0.0, proxies["transport"]).ravel()
    else:
        bw = np.repeat(_AREA_ROW, NLON)
    placed = bunkers * bw / bw.sum()
    out["fuel_bunkers"] += placed
    every = np.arange(NLAT * NLON)
    add_month("fuel_bunkers", every, placed, factors_for("transport", sea.nonzero()[0], 1.0))

    area = np.repeat(_AREA_ROW, NLON)
    components = {k: (v / area).reshape(NLAT, NLON) for k, v in out.items()}
    monthly_frames = {k: (v / area).reshape(12, NLAT, NLON) for k, v in frames.items()}
    return Allocation(components, report, monthly_frames)


def summarise(alloc: Allocation, energy: NationalEnergy) -> dict:
    """Global totals in TW: by source, engine and component, and the cascade's split."""
    area = d.cell_areas()
    tw = {k: float((v * area).sum() / 1e12) for k, v in alloc.components.items()}
    p, work, heat = d.cascade(alloc.components)
    primary = d.direct_equivalent(
        {s: sum(src[s] for src in energy.twh.values()) for s in d.SOURCES}
    )
    by_source = {s: d.twh_per_year_to_watts(v) / 1e12 for s, v in primary.items()}
    total_p = float((p * area).sum() / 1e12)
    return {
        "year": energy.year,
        "primary_tw": total_p,
        "useful_work_tw": float((work * area).sum() / 1e12),
        "waste_heat_tw": float((heat * area).sum() / 1e12),
        "useful_fraction": float((work * area).sum() / (p * area).sum()),
        "by_component_tw": tw,
        "by_source_tw": by_source,
        "by_engine_tw": d.by_engine(by_source),
        "unplaced_tw": sum(alloc.report["unplaced_w"].values()) / 1e12,
        "monthly_primary_tw": [
            float(((alloc.frames["p_base"][m] + alloc.frames["p_bldg"][m]) * area).sum() / 1e12)
            for m in range(12)
        ]
        if alloc.frames
        else [],
        "countries": len(energy.twh),
        "countries_estimated": len(energy.estimated),
        **{k: v for k, v in alloc.report.items() if k != "unplaced_w"},
        "unplaced": sorted(alloc.report["unplaced_w"]),
    }


# ---- the static product ----------------------------------------------------------------


def build_static(inputs: Path, year: int | None = None, edgar: Path | None = None):
    """Inputs folder -> (dataset of the annual component grids in W m-2, summary dict)."""
    energy = read_owid(inputs / "owid-energy-data.csv", year)
    grid = country_grid(inputs / "ne_50m_admin_0_countries.geojson")
    proxies = load_plants(inputs / "global_power_plant_database.csv")
    edgar_dir = edgar or inputs / "edgar"
    edgar_proxies, edgar_year = load_edgar(edgar_dir, energy.year)
    proxies.update(edgar_proxies)
    monthly, factor_years = load_edgar_monthly(edgar_dir)
    alloc = allocate(energy, grid, proxies, monthly)
    summary = summarise(alloc, energy)
    summary["edgar_year"] = edgar_year
    summary["factor_years"] = factor_years
    lat = 89.75 - 0.5 * np.arange(NLAT)
    lon = -179.75 + 0.5 * np.arange(NLON)
    ds = xr.Dataset(
        {
            **{k: (("lat", "lon"), v.astype("float32")) for k, v in alloc.components.items()},
            **{k: (("month", "lat", "lon"), v.astype("float32")) for k, v in alloc.frames.items()},
        },
        coords={"month": np.arange(1, 13), "lat": lat, "lon": lon},
        attrs={
            "title": "Technosphere primary power by component (annual) and by month",
            "units": "W m-2",
            "year": energy.year,
            "edgar_year": edgar_year if edgar_year is not None else -1,
            "factor_years": ",".join(map(str, factor_years)) or "none (flat)",
        },
    )
    for k in d.COMPONENTS:
        ds[k].attrs = {"units": "W m-2", "useful_fraction": d.USEFUL_FRACTION[k]}
    for k in FRAMES:
        ds[k].attrs = {"units": "W m-2"}
    return ds, summary


def write_static(ds: xr.Dataset, summary: dict, work: Path) -> Path:
    folder = work / "human"
    folder.mkdir(parents=True, exist_ok=True)
    year = int(ds.attrs["year"])
    path = folder / f"human_{year}.nc"
    tmp = path.with_suffix(".nc.tmp")
    ds.to_netcdf(tmp, encoding={k: {"zlib": True, "complevel": 4} for k in ds.data_vars})
    tmp.replace(path)
    (folder / f"summary_{year}.json").write_text(json.dumps(summary, indent=1))
    return path


# ---- the layers: a date and a climate frame (milestone 25) ------------------------------

HUMAN_START = date(2026, 7, 28)  # the first date given human layers (Anthony, 2026-11-01)
P_RANGE_TW = (12.0, 25.0)  # a day's world primary power outside this is an error
CLIM_FRAMES = (*(f"{m:02d}" for m in range(1, 13)), "year")
STATE_PREFIX = "state/human/"  # in the object store: the static grids and the normals
T_NORMAL = "t_normal.nc"  # 1991-2020 monthly-mean skin temperature, from the climate frames


@dataclass
class HumanStatic:
    """What the human layers are made from: the latest energy year's monthly frames and the
    1991-2020 skin-temperature normals (None until made; then the weather factor is 1)."""

    year: int
    frames: dict[str, np.ndarray]  # FRAMES -> (12, 360, 720) W m-2
    t_normal: np.ndarray | None = None  # (12, 360, 720) K
    factor_years: str = ""

    @classmethod
    def load(cls, work: Path) -> HumanStatic | None:
        folder = work / "human"
        files = sorted(folder.glob("human_[0-9][0-9][0-9][0-9].nc")) if folder.is_dir() else []
        if not files:
            return None
        with xr.open_dataset(files[-1]) as ds:
            if not set(FRAMES) <= set(ds.data_vars):
                return None  # a milestone 24 file without the monthly frames
            frames = {k: ds[k].values.astype("float64") for k in FRAMES}
            year, factor_years = int(ds.attrs["year"]), str(ds.attrs.get("factor_years", ""))
        t_normal = None
        if (folder / T_NORMAL).is_file():
            with xr.open_dataset(folder / T_NORMAL) as tn:
                t_normal = tn["t_skin"].values.astype("float64")
        return cls(year, frames, t_normal, factor_years)

    def month(self, m: int) -> tuple[np.ndarray, ...]:
        """(p_base, p_bldg, w_base, w_bldg) of calendar month m (1-12)."""
        return tuple(self.frames[k][m - 1] for k in FRAMES)

    def year_frame(self) -> tuple[np.ndarray, ...]:
        """The day-weighted mean of the months: the annual grid, exactly."""
        w = np.asarray(d.DAYS_IN_MONTH)[:, None, None] / sum(d.DAYS_IN_MONTH)
        return tuple((self.frames[k] * w).sum(axis=0) for k in FRAMES)

    @property
    def label(self) -> str:
        return f"{self.year} energy use"


def world_tw(p: np.ndarray) -> float:
    return float(np.nansum(p * d.cell_areas()) / 1e12)


def _fields(p, work, heat, bld) -> dict[str, d.LayerField]:
    """The four layers as LayerFields; human_ratio is masked where the wind is calm."""
    none = xr.DataArray(np.zeros(p.shape, bool))
    ratio, masked = d.human_ratio(p, bld)
    return {
        "human_q": d.LayerField(xr.DataArray(p), none),
        "human_work": d.LayerField(xr.DataArray(work), none),
        "human_heat": d.LayerField(xr.DataArray(heat), none),
        "human_ratio": d.LayerField(xr.DataArray(ratio), xr.DataArray(masked)),
    }


def day_layers(static: HumanStatic, day: date, skt, bld) -> dict[str, d.LayerField]:
    """A date's human layers: its month's frame, the buildings' part scaled by the day's
    skin temperature (K) against the month's normal. Raises ValueError if the world total is
    implausible, so a bad static file can't publish nonsense."""
    m = day.month
    if static.t_normal is not None:
        weather = d.weather_factor(np.asarray(skt, dtype="float64"), static.t_normal[m - 1])
    else:
        weather = np.ones((NLAT, NLON))
    p, work, heat = d.human_flows(*static.month(m), weather)
    total = world_tw(p)
    if not P_RANGE_TW[0] <= total <= P_RANGE_TW[1]:
        raise ValueError(f"human primary power {total:.2f} TW outside {P_RANGE_TW} TW")
    return _fields(p, work, heat, np.asarray(bld, dtype="float64"))


def frame_layers(static: HumanStatic, frame: str, bld) -> dict[str, d.LayerField]:
    """A climate frame's human layers ("01"-"12" or "year"): the typical month, no weather;
    the ratio against that frame's 1991-2020 mean dissipation."""
    parts = static.year_frame() if frame == "year" else static.month(int(frame))
    p, work, heat = d.human_flows(*parts, 1.0)
    return _fields(p, work, heat, np.asarray(bld, dtype="float64"))


def layer_codes(layers: dict[str, d.LayerField]) -> dict[str, np.ndarray]:
    """LayerFields -> {layer: (360, 720) uint16 codes} in each layer's own packing."""
    from .encode import quantise
    from .layers import LAYERS

    out = {}
    for lid, f in layers.items():
        s = LAYERS[lid]
        out[lid], _ = quantise(
            f.values.values, f.masked.values, *s.encode, log=s.log, step=s.resolution
        )
    return out


_STATIC_CACHE: dict[tuple, HumanStatic | None] = {}


def _static_for(work: Path) -> HumanStatic | None:
    """HumanStatic.load, cached while the files don't change (a backfill builds many dates)."""
    folder = work / "human"
    key = (
        tuple((p.name, p.stat().st_mtime_ns) for p in sorted(folder.glob("*.nc")))
        if folder.is_dir()
        else ()
    )
    if key not in _STATIC_CACHE:
        _STATIC_CACHE.clear()
        _STATIC_CACHE[key] = HumanStatic.load(work)
    return _STATIC_CACHE[key]


def for_build(day: date, skt, bld, work: Path, log: Callable[[str], None] = print) -> dict:
    """The human layers for `build_date`, or {} (before HUMAN_START, without the static file,
    or when they fail their check: the natural layers still publish)."""
    if day < HUMAN_START:
        return {}
    static = _static_for(work)
    if static is None:
        return {}
    try:
        return day_layers(static, day, skt, bld)
    except ValueError as e:
        log(f"::warning::{day}: human layers left out: {e}")
        return {}


# ---- adding the layers to what is already published ------------------------------------


def _decode_png(path: Path, lid: str) -> np.ndarray:
    from .encode import MASKED, NODATA, decode, png_to_ints
    from .layers import LAYERS

    s = LAYERS[lid]
    codes = png_to_ints(path.read_bytes())
    values = decode(codes, *s.encode, log=s.log, step=s.resolution).astype("float64")
    return np.where((codes == NODATA) | (codes == MASKED), np.nan, values)


def _decode_point(folder: Path, field: str) -> np.ndarray:
    from .encode import MASKED, NODATA, decode
    from .layers import EXTRAS
    from .points import read_point_field

    s = EXTRAS[field]
    codes = read_point_field(folder, field)
    values = decode(codes, *s.encode, step=s.resolution).astype("float64")
    return np.where((codes == NODATA) | (codes == MASKED), np.nan, values)


def t_normal_from_out(out: Path) -> np.ndarray | None:
    """The 1991-2020 monthly skin temperature (12, 360, 720) K from the published climate
    point chunks (their `t_skin` extra), or None without them."""
    months = []
    for m in range(1, 13):
        folder = out / "clim" / "points" / f"{m:02d}"
        if not folder.is_dir():
            return None
        months.append(_decode_point(folder, "t_skin"))
    return np.stack(months)


def write_t_normal(t: np.ndarray, work: Path) -> Path:
    folder = work / "human"
    folder.mkdir(parents=True, exist_ok=True)
    ds = xr.Dataset(
        {"t_skin": (("month", "lat", "lon"), t.astype("float32"), {"units": "K"})},
        coords={"month": np.arange(1, 13)},
        attrs={"title": "1991-2020 monthly-mean skin temperature (ERA5), from the climate frames"},
    )
    path = folder / T_NORMAL
    tmp = path.with_suffix(".nc.tmp")
    ds.to_netcdf(tmp, encoding={"t_skin": {"zlib": True, "complevel": 4}})
    tmp.replace(path)
    return path


def _put(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def apply_to_out(
    out: Path,
    work: Path,
    start: date = HUMAN_START,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> dict:
    """Add the human layers to a data root that is already published: every date from
    `start` that lacks them (or all with `force`) gets `fields/{date}/human_*.png` and its
    point chunks those fields (upgraded to the current layout); the climate frames get
    `clim/{frame}/human_*.png`, their point chunks, `clim/series` and `clim/year/series`, and
    `clim/clim.json` lists them with a `human` block. Then the human series and the manifest
    (last). Nothing else is touched. Returns counts."""
    from .encode import scalar_png
    from .layers import HUMAN
    from .points import _tiles, build_series, patch_point_fields
    from .publish import refresh_manifest

    static = HumanStatic.load(work)
    if static is None:
        raise FileNotFoundError(
            f"no technosphere grids with monthly frames in {work / 'human'}: run human-static"
        )
    if static.t_normal is None:
        t = t_normal_from_out(out)
        if t is None:
            log("::warning::no climate point chunks: the weather factor is 1 (typical months)")
        else:
            write_t_normal(t, work)
            static.t_normal = t
            log("wrote the 1991-2020 skin-temperature normals from the climate frames")
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    counts = {"dates": 0, "skipped": [], "frames": 0, "files": 0}

    for day in manifest.get("dates", []):
        if date.fromisoformat(day) < start:
            continue
        folder = out / "fields" / day
        if not force and all((folder / f"{lid}.png").is_file() for lid in HUMAN):
            continue
        bld_png = folder / "diss_bl.png"
        points = out / "points" / day
        if not bld_png.is_file() or not points.is_dir():
            counts["skipped"].append(day)
            log(f"::warning::{day}: no diss_bl.png or point chunks, left without human layers")
            continue
        try:
            layers = day_layers(
                static, date.fromisoformat(day), _decode_point(points, "t_skin"),
                _decode_png(bld_png, "diss_bl"),
            )  # fmt: skip
        except ValueError as e:
            counts["skipped"].append(day)
            log(f"::warning::{day}: {e}")
            continue
        codes = layer_codes(layers)
        for lid, c in codes.items():
            _put(folder / f"{lid}.png", scalar_png(c))
        counts["files"] += len(codes) + patch_point_fields(points, codes)
        counts["dates"] += 1

    index_path = out / "clim" / "clim.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text())
        by_frame: dict[str, dict[str, np.ndarray]] = {}
        for frame in CLIM_FRAMES:
            bld_png = out / "clim" / frame / "diss_bl.png"
            bld = (
                _decode_png(bld_png, "diss_bl")
                if bld_png.is_file()
                else np.full((NLAT, NLON), np.nan)
            )
            codes = layer_codes(frame_layers(static, frame, bld))
            for lid, c in codes.items():
                _put(out / "clim" / frame / f"{lid}.png", scalar_png(c))
            folder = out / "clim" / "points" / frame
            counts["files"] += len(codes) + (
                patch_point_fields(folder, codes) if folder.is_dir() else 0
            )
            by_frame[frame] = codes
            counts["frames"] += 1
        for lid in HUMAN:
            months = np.stack([by_frame[f"{m:02d}"][lid] for m in range(1, 13)])
            for (tx, ty), tile in _tiles(months):
                _put(out / "clim" / "series" / lid / f"{tx}_{ty}.bin", tile.tobytes())
            for (tx, ty), tile in _tiles(by_frame["year"][lid][None]):
                _put(out / "clim" / "year" / "series" / lid / f"{tx}_{ty}.bin", tile.tobytes())
            counts["files"] += 2 * 648
        index["layers"] = [*index["layers"], *(lid for lid in HUMAN if lid not in index["layers"])]
        index["human"] = {
            "year": static.year,
            "label": static.label,
            "months": f"typical months, EDGAR {static.factor_years}",
        }
        _put(index_path, json.dumps(index, indent=1).encode())

    counts["files"] += build_series(out, layers=list(HUMAN))
    refresh_manifest(out, add_layers=list(HUMAN))  # last: the front end reads it first
    log(
        f"human layers: {counts['dates']} dates, {counts['frames']} climate frames, "
        f"{counts['files']} files; skipped {len(counts['skipped'])}"
    )
    return counts


def download_static(store, work: Path, log: Callable[[str], None] = print) -> list[Path]:
    """Fetch the store's technosphere grids and normals (`state/human/`) that `work/human`
    doesn't have yet; local files are kept."""
    got = []
    for key in store.list(STATE_PREFIX):
        dest = work / "human" / key.removeprefix(STATE_PREFIX)
        if not dest.is_file() and store.get(key, dest):
            got.append(dest)
    log(f"downloaded {len(got)} technosphere file(s) from the store")
    return got


def upload_static(store, work: Path, log: Callable[[str], None] = print) -> list[str]:
    """Put the newest technosphere grids and the normals in the store (`state/human/`),
    where the daily job finds them."""
    folder = work / "human"
    files = sorted(folder.glob("human_[0-9][0-9][0-9][0-9].nc"))[-1:] + sorted(
        folder.glob(T_NORMAL)
    )
    keys = []
    for path in files:
        store.put(STATE_PREFIX + path.name, path)
        keys.append(STATE_PREFIX + path.name)
    log(f"uploaded {', '.join(keys) or 'nothing'}")
    return keys
