"""The ocean overlay: the two limbs of the Atlantic overturning (AMOC), from Copernicus Marine.

Source: the Copernicus Marine global analysis and forecast (GLO12, GLOBAL_ANALYSISFORECAST_PHY
_001_024), daily-mean currents u, v on 50 depth levels at 1/12 degree. GLO12 is a model that
assimilates satellite altimetry and sea-surface temperature, sea-ice and Argo profiles: the
satellites see only the surface, and the model carries what they see down to the sea floor.

For each published date, and separately for each limb (`layers.OCEAN_LIMBS`):

1. Fetch the date's u, v over the Atlantic box (`BOX`) and integrate each limb over depth
   at full resolution (`derived.limb_transports`): transport per metre of width (U, V) and
   the thickness of water in the limb H.
2. Diagnose the overturning across 26.5 N, Florida to Africa (RAPID's line), at full
   resolution: the streamfunction maximum and each limb's net northward transport, in Sv.
3. Average U, V, H onto the site's 0.5 degree grid, conservatively (land counts as no flow,
   so a cell's value is the water it carries divided by its width), and keep only the
   Atlantic (`basin_mask`). This small product is the state: `work/ocean/{date}.npz` here,
   `state/ocean/{date}.npz` in the store, so the 30-day mean never needs a re-download.
4. Encode the day and the 30-day mean ending on it: `{limb}.png` is the transport |(U, V)|
   (log packing; it sets how densely particles are drawn) and `{limb}_uv.png` the depth-mean
   velocity (U, V) / H (it moves them). The files go to `ocean/{date}/`, outside `fields/`
   so a rebuild of the ERA5 date can't delete them, and the manifest's `ocean` block records
   which dates have them, last.

The daily job runs this after the ERA5 build (`run_ocean_daily`), never at the same time, so
the two never write the manifest at once. A fetch that fails is logged and retried the next
day; the dates it could build are still published.
"""

from __future__ import annotations

import json
import shutil
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from . import derived as d
from .encode import quantise, scalar_png, vector_png
from .info import OCEAN_INFO
from .layers import OCEAN_LIMBS, LimbSpec
from .publish import _range, _read_manifest, _swap_in, _write_manifest
from .store import Store

PRODUCT_ID = "GLOBAL_ANALYSISFORECAST_PHY_001_024"
DATASET_ID = "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m"
VARIABLES = ("uo", "vo")


@dataclass(frozen=True)
class Box:
    west: float
    east: float
    south: float
    north: float


# The Atlantic from the Gulf of Mexico to the Nordic Seas and Fram Strait, and south to 40 S
# (south of that the Atlantic opens into the Southern Ocean). About 0.4-0.9 GB a day.
BOX = Box(west=-100.0, east=25.0, south=-40.0, north=80.0)
SECTION_LAT = 26.5  # RAPID
SECTION_LON = (-81.0, -13.0)  # Florida to Africa; leaves out the Gulf of Mexico
WINDOW_DAYS = 30
MIN_WINDOW_DAYS = 24  # fewer days than this in the window: no 30-day mean for the date
MAX_FETCH = 15  # downloads per run; a first backfill of 119 days takes about 8 runs
OCEAN_MIN_FRACTION = 0.3  # 0.5-degree cells with less ocean than this are land
SEED = (-30.0, 30.0)  # lon, lat in the open North Atlantic, where the basin fill starts
# The continental divide of Central America, south to north (lon, lat). Cells west of it are
# Pacific, whatever the 0.5-degree land mask lets the basin fill reach through Panama.
PACIFIC_DIVIDE = (
    (-77.0, -60.0), (-77.0, 7.5), (-79.5, 9.0), (-84.3, 10.0), (-85.5, 12.0),
    (-88.0, 14.5), (-92.0, 16.0), (-95.0, 17.0), (-100.0, 18.5),
)  # fmt: skip

NLAT, NLON = 360, 720
GRID_LAT = 89.75 - 0.5 * np.arange(NLAT)
GRID_LON = -179.75 + 0.5 * np.arange(NLON)
SECTION_GRID_LAT = np.arange(-40.0, 80.0 + 1e-6, 0.5)  # latitude bins of the latitude-depth section
SECTION_KEYS = ("psi_max_sv", "z_max_m", "amoc_upper_sv", "amoc_deep_sv")
SUFFIX = {"daily": "", "mean": "_30d"}
PART_SUFFIX = {"full": "", "ov": "_ov"}  # ov: the overturning part, gyres removed


# ---- fetching and reading GLO12 --------------------------------------------------------


def check_credentials() -> bool:
    """Whether the Copernicus Marine credentials (COPERNICUSMARINE_SERVICE_USERNAME and
    _PASSWORD) are valid. Checked first, so a bad account fails before anything changes."""
    import copernicusmarine

    return bool(copernicusmarine.login(check_credentials_valid=True))


def fetch_day(day: date, dest: Path, subset: Callable | None = None) -> Path:
    """Download one day of GLO12 u, v over `BOX`, all depths, as NetCDF. Returns its path.

    Daily means are stamped at the start of their day; asking for the whole UTC day works
    whichever stamp a dataset version uses, and `load_day` checks one time step came back.
    """
    if subset is None:
        import copernicusmarine

        subset = copernicusmarine.subset
    dest.mkdir(parents=True, exist_ok=True)
    name = f"glo12_{day.isoformat()}.nc"
    subset(
        dataset_id=DATASET_ID,
        variables=list(VARIABLES),
        minimum_longitude=BOX.west,
        maximum_longitude=BOX.east,
        minimum_latitude=BOX.south,
        maximum_latitude=BOX.north,
        minimum_depth=0.0,
        maximum_depth=6000.0,
        start_datetime=f"{day.isoformat()}T00:00:00",
        end_datetime=f"{day.isoformat()}T23:59:59",
        coordinates_selection_method="inside",
        output_directory=str(dest),
        output_filename=name,
        overwrite=True,
        disable_progress_bar=True,
    )
    path = dest / name
    if not path.is_file():
        raise FileNotFoundError(f"Copernicus Marine returned no file for {day}")
    return path


def load_day(path: Path):
    """(u, v, depth, lat, lon) from a GLO12 subset. u and v stay lazy (level-first), so the
    depth integrals read one level at a time."""
    import xarray as xr

    ds = xr.open_dataset(path)
    if ds.sizes.get("time", 1) != 1:
        raise ValueError(f"{path.name}: expected one daily mean, got {ds.sizes['time']} times")
    u, v = ds["uo"], ds["vo"]
    if "time" in u.dims:
        u, v = u.isel(time=0), v.isel(time=0)
    u = u.transpose("depth", "latitude", "longitude")
    v = v.transpose("depth", "latitude", "longitude")
    return u, v, ds["depth"].values, ds["latitude"].values, ds["longitude"].values


# ---- onto the 0.5 degree grid ----------------------------------------------------------


def overlap(centres, step: float, lo, hi) -> np.ndarray:
    """(n_dst, n_src): the fraction of each source cell (centre +/- step / 2) that lies in
    each destination interval [lo, hi). Point-centred sources on cell edges count half."""
    c = np.asarray(centres, dtype="float64")[None, :]
    lo = np.asarray(lo, dtype="float64")[:, None]
    hi = np.asarray(hi, dtype="float64")[:, None]
    return np.clip(np.minimum(c + step / 2, hi) - np.maximum(c - step / 2, lo), 0, None) / step


@dataclass(frozen=True)
class Regridder:
    """Area-weighted averages of a source grid over the 0.5-degree cells it covers."""

    rows: np.ndarray  # (NLAT, n_lat_src): overlap x cos(lat)
    cols: np.ndarray  # (NLON, n_lon_src): overlap
    norm: np.ndarray  # (NLAT, NLON): the covered area of each cell, in the same units
    covered: np.ndarray  # (NLAT, NLON) bool: at least half the cell has source data

    def mean(self, x) -> np.ndarray:
        """Cell means; NaN counts as zero (land: no flow), cells outside the source NaN."""
        x = np.nan_to_num(np.asarray(x, dtype="float64"))
        with np.errstate(divide="ignore", invalid="ignore"):
            out = self.rows @ x @ self.cols.T / self.norm
        return np.where(self.covered, out, np.nan)


def regridder(lat, lon) -> Regridder:
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    step = float(abs(lon[1] - lon[0]))
    o_lat = overlap(lat, step, GRID_LAT - 0.25, GRID_LAT + 0.25)
    o_lon = overlap(lon, step, GRID_LON - 0.25, GRID_LON + 0.25)
    rows = o_lat * np.cos(np.deg2rad(lat))[None, :]
    ones = np.ones((lat.size, lon.size))
    norm = rows @ ones @ o_lon.T
    full = (0.5 / step) ** 2  # source cells in a whole 0.5-degree cell
    covered = (o_lat.sum(1)[:, None] * o_lon.sum(1)[None, :]) >= full / 2
    return Regridder(rows, o_lon, norm, covered)


def _pacific(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    divide_lon, divide_lat = np.array(PACIFIC_DIVIDE).T
    line = np.interp(lat, divide_lat, divide_lon)
    return (lat <= divide_lat[-1]) & (lon < line)


def basin_mask(ocean_fraction: np.ndarray, seed=SEED) -> np.ndarray:
    """The Atlantic on the 0.5-degree grid: cells with at least OCEAN_MIN_FRACTION of ocean
    that connect (through edges, not corners) to `seed`, east of the Central American divide."""
    lat, lon = np.meshgrid(GRID_LAT, GRID_LON, indexing="ij")
    sea = np.nan_to_num(ocean_fraction) >= OCEAN_MIN_FRACTION
    sea &= ~_pacific(lat, lon)
    j0 = int(np.argmin(abs(GRID_LAT - seed[1])))
    i0 = int(np.argmin(abs(GRID_LON - seed[0])))
    basin = np.zeros_like(sea)
    if not sea[j0, i0]:
        return basin
    basin[j0, i0] = True
    todo = deque([(j0, i0)])
    while todo:
        j, i = todo.popleft()
        for jj, ii in ((j - 1, i), (j + 1, i), (j, i - 1), (j, i + 1)):
            if 0 <= jj < NLAT and 0 <= ii < NLON and sea[jj, ii] and not basin[jj, ii]:
                basin[jj, ii] = True
                todo.append((jj, ii))
    return basin


# ---- one day -------------------------------------------------------------------------


@dataclass
class OceanDay:
    """A day (or a window mean) on the 0.5-degree grid, plus the 26.5 N diagnostics."""

    ocean_fraction: np.ndarray  # (NLAT, NLON)
    limbs: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]  # id -> (U, V, H)
    section: dict[str, float]  # SECTION_KEYS
    days: int = 1  # how many days were averaged
    # The Atlantic's streamfunction on the latitude-depth section (Sv, (nz, len(SECTION_GRID_LAT))
    # at the levels' bottom edges), where the basin holds water, and the levels' depths (m).
    # None for a day saved before the section existed.
    psi: np.ndarray | None = None
    psi_wet: np.ndarray | None = None
    depth: np.ndarray | None = None


def reduce_day(u, v, depth, lat, lon) -> OceanDay:
    """Depth integrals, the 26.5 N overturning and the 0.5-degree averages of one day."""
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    specs = list(OCEAN_LIMBS.values())
    integrals = d.limb_transports(u, v, depth, [(s.top_m, s.bottom_m) for s in specs])
    rg = regridder(lat, lon)
    wet = np.isfinite(np.asarray(u[0], dtype="float64"))
    ocean_fraction = rg.mean(wet.astype("float64"))
    j = int(np.argmin(abs(lat - SECTION_LAT)))
    cols = np.flatnonzero((lon >= SECTION_LON[0]) & (lon <= SECTION_LON[1]))
    edges, psi = d.overturning(
        np.asarray(v[:, j, cols.min() : cols.max() + 1]), depth, lon[cols], lat[j]
    )
    strength, z = d.amoc_strength(edges, psi)
    section = {"psi_max_sv": strength, "z_max_m": z}
    limbs = {}
    for s, (uu, vv, h) in zip(specs, integrals, strict=True):
        section[f"{s.id}_sv"] = d.section_transport(vv[j, cols], lon[cols], lat[j])
        limbs[s.id] = (rg.mean(uu), rg.mean(vv), rg.mean(h))
    # The basin on the model's own grid, for the zonal integral at every latitude.
    basin = basin_mask(ocean_fraction)
    rows = np.clip(np.floor((90.0 - lat) / 0.5).astype(int), 0, NLAT - 1)
    cols_native = np.clip(np.floor((lon + 180.0) / 0.5).astype(int), 0, NLON - 1)
    psi, psi_wet = d.latitude_overturning(
        v, depth, lat, lon, basin[np.ix_(rows, cols_native)], SECTION_GRID_LAT
    )
    return OceanDay(
        ocean_fraction, limbs, section, psi=psi, psi_wet=psi_wet, depth=np.asarray(depth, "float64")
    )


def window_mean(days: list[OceanDay]) -> OceanDay:
    """The mean of several days: transports and thicknesses averaged, so the velocity of the
    mean is mean(U) / mean(H). The 26.5 N numbers are the means of the daily ones."""
    stack = lambda f: np.mean(np.stack([f(x) for x in days]), axis=0)  # noqa: E731
    limbs = {
        lid: tuple(stack(lambda x, lid=lid, k=k: x.limbs[lid][k]) for k in range(3))
        for lid in days[0].limbs
    }
    section = {k: float(np.mean([x.section[k] for x in days])) for k in SECTION_KEYS}
    with_psi = [x for x in days if x.psi is not None]
    psi = np.mean([x.psi for x in with_psi], axis=0) if with_psi else None
    wet = np.any([x.psi_wet for x in with_psi], axis=0) if with_psi else None
    return OceanDay(
        days[0].ocean_fraction, limbs, section, days=len(days), psi=psi, psi_wet=wet,
        depth=with_psi[0].depth if with_psi else None,
    )  # fmt: skip


def save_day(path: Path, day: OceanDay) -> None:
    arrays = {"ocean_fraction": day.ocean_fraction.astype("float32")}
    for lid, (uu, vv, h) in day.limbs.items():
        arrays |= {f"{lid}_U": uu, f"{lid}_V": vv, f"{lid}_H": h}
    arrays = {k: np.asarray(a, dtype="float32") for k, a in arrays.items()}
    if day.psi is not None:
        arrays |= {"psi": day.psi.astype("float32"), "depth": np.asarray(day.depth, "float32")}
        arrays["psi_wet"] = day.psi_wet.astype("uint8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez_compressed(tmp, **arrays, section=np.array([day.section[k] for k in SECTION_KEYS]))
    tmp.replace(path)


def load_saved(path: Path) -> OceanDay:
    with np.load(path, allow_pickle=False) as z:
        limbs = {
            lid: tuple(z[f"{lid}_{c}"].astype("float64") for c in "UVH") for lid in OCEAN_LIMBS
        }
        section = dict(zip(SECTION_KEYS, (float(x) for x in z["section"]), strict=True))
        has_psi = "psi" in z.files
        return OceanDay(
            z["ocean_fraction"].astype("float64"), limbs, section,
            psi=z["psi"].astype("float64") if has_psi else None,
            psi_wet=z["psi_wet"].astype(bool) if has_psi else None,
            depth=z["depth"].astype("float64") if has_psi else None,
        )  # fmt: skip


# ---- encoding and publishing -----------------------------------------------------------


def encode_limb(spec: LimbSpec, uu, vv, h, basin) -> tuple[bytes, bytes]:
    """(`{limb}.png`, `{limb}_uv.png`): transport magnitude and depth-mean velocity.

    Outside the box: no data. Inside it, land, other basins and water too thin for the limb
    are masked."""
    outside = ~np.isfinite(h)
    ub, vb, thin = d.depth_mean_velocity(uu, vv, h, spec.min_thickness_m)
    masked = ~outside & (~basin | thin)
    speed = np.where(outside, np.nan, np.hypot(uu, vv))
    mag, _ = quantise(speed, masked, *spec.encode, log=True, step=spec.resolution)
    cu, _ = quantise(ub, masked, *spec.uv_encode, step=spec.uv_resolution)
    cv, _ = quantise(vb, masked, *spec.uv_encode, step=spec.uv_resolution)
    return scalar_png(mag), vector_png(cu, cv)


def encode_section(psi: np.ndarray, wet: np.ndarray, depth) -> bytes:
    """`section{avg}.json`: the streamfunction in tenths of a Sv, level-major (rows are the
    model's levels, columns the latitude bins); null where the basin has no water. Also the
    two limbs' net transport at each latitude (`upper_sv`, `deep_sv`, Sv, null where dry)."""
    upper, deep = d.limb_transports_by_latitude(psi, depth)
    dry = ~np.asarray(wet).any(axis=0)
    belt = lambda x: [None if n else round(float(v), 2) for v, n in zip(x, dry, strict=True)]  # noqa: E731
    tenths = np.rint(np.asarray(psi, dtype="float64") * 10).astype(int)
    rows = [
        [int(x) if w else None for x, w in zip(r, wr, strict=True)]
        for r, wr in zip(tenths, wet, strict=True)
    ]
    body = {"psi": rows, "upper_sv": belt(upper), "deep_sv": belt(deep)}
    return json.dumps(body, separators=(",", ":")).encode()


def encode_ocean(daily: OceanDay, mean: OceanDay | None) -> dict[str, bytes]:
    """Every file of one date: each limb, daily and (if there is one) its 30-day mean."""
    basin = basin_mask(daily.ocean_fraction)
    files: dict[str, bytes] = {}
    for avg, x in (("daily", daily), ("mean", mean)):
        if x is None:
            continue
        for lid, (uu, vv, h) in x.limbs.items():
            png, uv = encode_limb(OCEAN_LIMBS[lid], uu, vv, h, basin)
            files[f"{lid}{SUFFIX[avg]}.png"] = png
            files[f"{lid}{SUFFIX[avg]}_uv.png"] = uv
        if avg == "mean":
            part = d.overturning_part([x.limbs[lid] for lid in OCEAN_LIMBS])
            for lid, (uu, vv, h) in zip(OCEAN_LIMBS, part, strict=True):
                png, uv = encode_limb(OCEAN_LIMBS[lid], uu, vv, h, basin)
                files[f"{lid}_30d{PART_SUFFIX['ov']}.png"] = png
                files[f"{lid}_30d{PART_SUFFIX['ov']}_uv.png"] = uv
        if x.psi is not None:
            files[f"section{SUFFIX[avg]}.json"] = encode_section(x.psi, x.psi_wet, x.depth)
    return files


def _rounded(section: dict[str, float]) -> dict[str, float]:
    return {k: round(float(section[k]), 2) for k in SECTION_KEYS}


def date_entry(
    daily: OceanDay, mean: OceanDay | None, days_in_window: int, psi_days: int = 0
) -> dict:
    return {
        "window_days": days_in_window,
        # The latitude-depth section: the days of the window that have it, and which averages
        # were drawn (the mean needs MIN_WINDOW_DAYS of them).
        "psi_days": psi_days,
        "belt": True,  # the section files carry the limbs' transport by latitude
        "ov": mean is not None,  # the mean also has the overturning-part files (gyres removed)
        "section": {"daily": daily.psi is not None, "mean": bool(mean and mean.psi is not None)},
        "daily": _rounded(daily.section),
        "mean": _rounded(mean.section) if mean is not None else None,
    }


def _limb_meta(s: LimbSpec) -> dict:
    return {
        "title": s.title,
        "colour": s.colour,
        "top_m": s.top_m,
        "bottom_m": None if s.bottom_m == float("inf") else s.bottom_m,
        "units": s.units,
        "uv_units": s.uv_units,
        "display": list(s.display),
        "encode": _range(*s.encode, s.resolution, log=True),
        "uv_encode": _range(*s.uv_encode, s.uv_resolution),
        "speed_hi": s.speed_hi,
        "density_ref": s.density_ref,
    }


def section_grid(depth) -> dict:
    """The latitude-depth section's grid: the latitude bins and the model's levels (m)."""
    return {
        "lat0": float(SECTION_GRID_LAT[0]),
        "dlat": float(SECTION_GRID_LAT[1] - SECTION_GRID_LAT[0]),
        "n_lat": len(SECTION_GRID_LAT),
        "depth_edges_m": [round(float(x), 1) for x in d.level_edges(depth)],
        "unit_sv": 0.1,
    }


def ocean_block(dates: dict[str, dict], depth=None, grid: dict | None = None) -> dict:
    """The manifest's `ocean` block. `grid` (the section's) is carried forward when this run
    saw no day with a depth axis."""
    grid = section_grid(depth) if depth is not None else grid
    return {
        "product": PRODUCT_ID,
        "dataset": DATASET_ID,
        "split_m": d.AMOC_SPLIT_M,
        "window_days": WINDOW_DAYS,
        "section": {"lat": SECTION_LAT, "lon": list(SECTION_LON)},
        "files": {
            "field": "ocean/{date}/{limb}{avg}{part}.png",
            "uv": "ocean/{date}/{limb}{avg}{part}_uv.png",
            "section": "ocean/{date}/section{avg}.json",
            "avg": dict(SUFFIX),
            "part": dict(PART_SUFFIX),
        },
        "section_grid": grid,
        "limbs": {lid: _limb_meta(s) for lid, s in OCEAN_LIMBS.items()},
        "dates": dict(sorted(dates.items())),
        "info": asdict(OCEAN_INFO),
        "credit": (
            "Generated using E.U. Copernicus Marine Service Information: Global Ocean Physics "
            "Analysis and Forecast (GLO12), doi:10.48670/moi-00016."
        ),
    }


def write_ocean_manifest(out: Path, dates: dict[str, dict], depth=None) -> None:
    """Rewrite the manifest's `ocean` block, keeping everything else as it is."""
    manifest = _read_manifest(out)
    published = set(manifest.get("dates", []))
    previous = (manifest.get("ocean") or {}).get("section_grid")
    manifest["ocean"] = ocean_block(
        {k: v for k, v in dates.items() if k in published}, depth, previous
    )
    _write_manifest(out, manifest)


# ---- the run -------------------------------------------------------------------------


@dataclass
class OceanResult:
    fetched: list[date] = field(default_factory=list)
    built: list[str] = field(default_factory=list)
    failed: dict[date, str] = field(default_factory=dict)
    saved: list[Path] = field(default_factory=list)  # new daily state files


def _window(day: date) -> list[date]:
    return [day - timedelta(days=k) for k in range(WINDOW_DAYS)]


def run_ocean(
    out: Path,
    work: Path,
    max_fetch: int = MAX_FETCH,
    fetch: Callable[[date, Path], Path] = fetch_day,
    load: Callable = load_day,
    log: Callable[[str], None] = lambda _m: None,
) -> OceanResult:
    """Bring the ocean overlay up to date for the dates in `out`'s manifest.

    Downloads at most `max_fetch` days: first the missing published dates themselves, newest
    first, then the rest of their 30-day windows. A date is (re)built when it is new or its
    window has filled in since it was last built. The manifest's `ocean` block is written last.
    """
    result = OceanResult()
    manifest = _read_manifest(out)
    if not manifest.get("dates"):
        log("ocean: no published dates yet")
        return result
    dates = [date.fromisoformat(x) for x in manifest["dates"]]
    entries: dict[str, dict] = dict((manifest.get("ocean") or {}).get("dates", {}))
    state = work / "ocean"
    saved = lambda day: state / f"{day.isoformat()}.npz"  # noqa: E731

    section_known: dict[Path, bool] = {}

    def has_section(day: date) -> bool:
        """The saved day carries the latitude-depth section (older saves don't)."""
        path = saved(day)
        if not path.is_file():
            return False
        if path not in section_known:
            with np.load(path, allow_pickle=False) as z:
                section_known[path] = "psi" in z.files
        return section_known[path]

    def stale(day: date) -> bool:
        entry = entries.get(day.isoformat())
        return (
            entry is None
            or entry.get("window_days", 0) < WINDOW_DAYS
            or entry.get("psi_days", 0) < entry["window_days"]
            or not entry.get("belt")
            or (entry.get("mean") is not None and not entry.get("ov"))
        )

    todo = [x for x in sorted(dates, reverse=True) if stale(x)]
    wanted = list(dict.fromkeys([*todo, *(w for x in todo for w in _window(x))]))
    # A day saved before the section existed is fetched again (it still serves until then).
    missing = [x for x in wanted if not has_section(x)][:max_fetch]
    for day in missing:
        try:
            nc = fetch(day, state / "raw")
            try:
                save_day(saved(day), reduce_day(*load(nc)))
            finally:
                Path(nc).unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001 - one bad day must not stop the others
            result.failed[day] = f"{type(e).__name__}: {e}"
            log(f"ocean {day}: not fetched: {result.failed[day]}")
            continue
        section_known.pop(saved(day), None)
        result.fetched.append(day)
        result.saved.append(saved(day))
        log(f"ocean {day}: fetched")

    depth = None
    for day in todo:
        if not saved(day).is_file():
            continue
        key = day.isoformat()
        window = [x for x in _window(day) if saved(x).is_file()]
        psi_days = sum(has_section(x) for x in window)
        if (
            key in entries
            and entries[key].get("window_days") == len(window)
            and entries[key].get("psi_days") == psi_days
            and entries[key].get("belt")
            and (entries[key].get("mean") is None or entries[key].get("ov"))
        ):
            continue  # nothing new in its window
        daily = load_saved(saved(day))
        mean = (
            window_mean([load_saved(saved(x)) for x in window])
            if len(window) >= MIN_WINDOW_DAYS
            else None
        )
        if mean is not None and psi_days < MIN_WINDOW_DAYS:
            mean.psi = mean.psi_wet = None  # too few days with the section for a mean of it
        if daily.depth is not None:
            depth = daily.depth
        _swap_in(out / "ocean", key, encode_ocean(daily, mean))
        entries[key] = date_entry(daily, mean, len(window), psi_days)
        result.built.append(key)
        s = entries[key]["daily"]
        log(
            f"ocean {key}: built ({len(window)} of {WINDOW_DAYS} days in the window); "
            f"AMOC at 26.5 N {s['psi_max_sv']:.1f} Sv at {s['z_max_m']:.0f} m"
        )

    keep = {x.isoformat() for x in dates}
    if (out / "ocean").is_dir():
        for p in (out / "ocean").iterdir():
            if p.is_dir() and not p.name.startswith(".") and p.name not in keep:
                shutil.rmtree(p)
    oldest = min(dates) - timedelta(days=WINDOW_DAYS)
    if state.is_dir():
        for p in state.glob("*.npz"):
            if date.fromisoformat(p.stem) < oldest:
                p.unlink()
    write_ocean_manifest(out, entries, depth)  # last
    return result


STATE_PREFIX = "state/ocean/"


def run_ocean_daily(
    store: Store,
    out: Path,
    work: Path,
    max_fetch: int = MAX_FETCH,
    log: Callable[[str], None] = lambda _m: None,
    fetch: Callable[[date, Path], Path] = fetch_day,
    load: Callable = load_day,
    check: Callable[[], bool] = check_credentials,
) -> OceanResult:
    """The daily job's ocean step, on a runner that is gone afterwards: check the Copernicus
    Marine account, bring back the manifest and the saved days, run, save the new days to
    the store, then publish (ocean files first, manifest last)."""
    from .deploy import MANIFEST, upload

    if not check():
        raise RuntimeError("Copernicus Marine credentials are missing or not valid")
    if not store.get(MANIFEST, out / MANIFEST):
        log("ocean: the store has no manifest yet: nothing to do")
        return OceanResult()
    manifest = json.loads((out / MANIFEST).read_text())
    if not manifest.get("dates"):
        return OceanResult()
    oldest = date.fromisoformat(min(manifest["dates"])) - timedelta(days=WINDOW_DAYS)
    remote = store.list(STATE_PREFIX)
    keep, expired = [], []
    for key in remote:
        stem = key.removeprefix(STATE_PREFIX).removesuffix(".npz")
        try:
            (keep if date.fromisoformat(stem) >= oldest else expired).append(key)
        except ValueError:
            continue
    for key in keep:
        store.get(key, work / "ocean" / key.removeprefix(STATE_PREFIX))
    log(f"ocean: {len(keep)} saved days downloaded")
    result = run_ocean(out, work, max_fetch, fetch=fetch, load=load, log=log)
    for p in result.saved:
        store.put(STATE_PREFIX + p.name, p)
    store.delete(expired)
    if result.built or manifest.get("ocean") != _read_manifest(out).get("ocean"):
        upload(store, out, log)
    return result
