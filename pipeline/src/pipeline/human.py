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
import io
import json
import re
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
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


def _get(url: str, opener: Callable = urllib.request.urlopen) -> bytes:
    with opener(url, timeout=300) as r:
        return r.read()


def fetch_inputs(folder: Path, edgar: bool = True, opener: Callable = urllib.request.urlopen):
    """Download the inputs into `folder` (existing files are kept). EDGAR zips are extracted
    into `folder/edgar/{sector}/`. Returns the paths written."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, url in URLS.items():
        if not (folder / name).is_file():
            (folder / name).write_bytes(_get(url, opener))
            written.append(folder / name)
    if edgar:
        for sector in EDGAR_DOWNLOAD:
            target = folder / "edgar" / sector
            if target.is_dir() and any(target.rglob("*.nc")):
                continue
            data = _get(EDGAR_URL.format(release=EDGAR_RELEASE, sector=sector), opener)
            written += _extract_nc(data, target)
    return written


def _extract_nc(data: bytes, target: Path) -> list[Path]:
    """Extract only the NetCDF files of an untrusted zip, flattened into `target`."""
    target.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if info.is_dir() or not name.endswith(".nc") or name.startswith("."):
                continue
            path = target / name
            path.write_bytes(z.read(info))
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


def _edgar_field(path: Path) -> np.ndarray:
    with xr.open_dataset(path) as ds:
        var = next(v for v in ds.data_vars.values() if v.ndim >= 2)
        lat = next(n for n in var.dims if n.lower().startswith("lat"))
        lon = next(n for n in var.dims if n.lower().startswith("lon"))
        other = [n for n in var.dims if n not in (lat, lon)]
        data = var.sum(dim=other) if other else var  # monthly files: the year's sum
        data = data.transpose(lat, lon)
        units = str(var.attrs.get("units", "")).replace(" ", "")
        per_area = "m-2" in units or "/m2" in units or "m^-2" in units
        return to_half_degree(data.values, ds[lat].values, ds[lon].values, per_area)


def load_edgar(folder: Path, year: int) -> tuple[dict[str, np.ndarray], int | None]:
    """EDGAR CO2 sector gridmaps in `folder` (searched recursively) -> {proxy: (360, 720)}
    summed per proxy, for the latest year <= `year` that the files have. Returns the year used
    (None when there are no files)."""
    found: dict[int, list[tuple[str, Path]]] = {}
    for p in sorted(folder.rglob("*.nc")) if folder.is_dir() else []:
        sector = _edgar_sector(p)
        years = [int(y) for y in _YEAR.findall(p.name)]
        if sector and years:
            found.setdefault(years[-1], []).append((sector, p))
    usable = [y for y in found if y <= year]
    if not usable:
        return {}, None
    used = max(usable)
    out: dict[str, np.ndarray] = {}
    for sector, p in found[used]:
        out[sector] = out.get(sector, 0) + _edgar_field(p)
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
            col = min(int((((lon + 180.0) % 360.0)) / 0.5), NLON - 1)
            out[kind][row, col] += mw
    return out


# ---- allocation ------------------------------------------------------------------------


@dataclass
class Allocation:
    components: dict[str, np.ndarray]  # W m-2, (360, 720)
    report: dict


def allocate(
    energy: NationalEnergy,
    grid: CountryGrid,
    proxies: dict[str, np.ndarray],
) -> Allocation:
    """Spread every country's components over its cells (see the module docstring)."""
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
    by_code = {c: i for i, c in enumerate(grid.codes)}
    flat = {k: v.ravel() for k, v in proxies.items()}
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
            np.add.at(out[name], cells, value * weights / weights.sum())

    # Bunkers: worldwide, by transport emissions over the open ocean (or evenly by area).
    if "transport" in proxies and proxies["transport"][~land].sum() > 0:
        bw = np.where(land, 0.0, proxies["transport"]).ravel()
    else:
        bw = np.repeat(_AREA_ROW, NLON)
    out["fuel_bunkers"] += bunkers * bw / bw.sum()

    area = np.repeat(_AREA_ROW, NLON)
    components = {k: (v / area).reshape(NLAT, NLON) for k, v in out.items()}
    return Allocation(components, report)


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
    edgar_proxies, edgar_year = load_edgar(edgar or inputs / "edgar", energy.year)
    proxies.update(edgar_proxies)
    alloc = allocate(energy, grid, proxies)
    summary = summarise(alloc, energy)
    summary["edgar_year"] = edgar_year
    lat = 89.75 - 0.5 * np.arange(NLAT)
    lon = -179.75 + 0.5 * np.arange(NLON)
    ds = xr.Dataset(
        {k: (("lat", "lon"), v.astype("float32")) for k, v in alloc.components.items()},
        coords={"lat": lat, "lon": lon},
        attrs={
            "title": "Technosphere primary power by component, annual mean",
            "units": "W m-2",
            "year": energy.year,
            "edgar_year": edgar_year if edgar_year is not None else -1,
        },
    )
    for k in d.COMPONENTS:
        ds[k].attrs = {"units": "W m-2", "useful_fraction": d.USEFUL_FRACTION[k]}
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
