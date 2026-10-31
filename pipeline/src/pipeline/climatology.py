"""The 1991-2020 monthly climatology, from ERA5 monthly means.

Fetching works like the daily data: requests are submitted without waiting and collected on
a later run (state in `raw/clim/pending.json`). Each request covers five years of the raw
inputs; when one arrives it is reduced straight away to per-calendar-month sums on the
0.5 degree grid (`work/clim/sums_{first}_{last}.nc`) and the download is deleted, so the
~7.5 GB of monthly fields never sit on disk at once. The fields go through the same
conversion as the daily data (`convert.tidy_dataset`: units, sign flips, conservative
regrid), which is valid because monthly-mean accumulations are mean daily accumulations.

Once all six chunks are in, `build_climatology` averages them per calendar month and runs
the layer formulas on the monthly means (`climatology_layers`). That is exact for layers
that are linear in the inputs and an approximation for the derived ones, which the info
panels say. Vector layers get no climatology: the speed of the mean wind is far below the
mean of daily speeds (see docs/DECISIONS.md, 2026-10-19).
"""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import numpy as np
import xarray as xr

from .convert import tidy_dataset
from .derived import compute_layers, radiative_summary
from .fetch import _FAILED, VARIABLES, FetchSpec, submit
from .layers import ANOMALY
from .load import NC_TO_KEY

MONTHLY = "reanalysis-era5-single-levels-monthly-means"
PRESSURE_MONTHLY = "reanalysis-era5-pressure-levels-monthly-means"  # confirmed 2026-10-24
FIRST_YEAR, LAST_YEAR = 1991, 2020
CHUNK_YEARS = 5
MAX_QUEUED = 2
# Raw inputs of every natural non-vector layer, plus the static land-sea mask.
CLIM_KEYS = (
    "tsr",
    "ttr",
    "ssr",
    "slhf",
    "sshf",
    "bld",
    "tp",
    "skt",
    "tcwv",
    "p59.162",
    "p86.162",
    "lsm",
)
CLIM_LAYERS = ANOMALY
_WIND_KEYS = ("u10", "v10", "u100", "v100", "u250", "v250")


@dataclass(frozen=True)
class Part:
    """One set of monthly-means requests. Each part is requested and reduced on its own and
    its sums are merged by key in `monthly_means`, so adding a variable never re-fetches the
    ones already in `work/clim/`."""

    name: str
    collection: str
    keys: tuple[str, ...]
    extra: dict = dc_field(default_factory=dict)  # request items beyond the common ones

    def sums_name(self, first: int, last: int) -> str:
        stem = "sums" if self.name == "main" else f"sums_{self.name}"
        return f"{stem}_{first}_{last}.nc"

    def request_name(self, first: int, last: int) -> str:
        stem = "clim" if self.name == "main" else f"clim_{self.name}"
        return f"{stem}_{first}_{last}.zip"


MAIN = Part("main", MONTHLY, CLIM_KEYS)
# 2026-10-24 (proposal v2): surface net longwave for `net_sfc`, and the winds for the
# mean-flow particles. The pressure-level winds come from a different dataset.
SURFACE = Part("surface", MONTHLY, ("str", "u10", "v10", "u100", "v100"))
PRESSURE = Part("pressure", PRESSURE_MONTHLY, ("u250", "v250"), {"pressure_level": ["250"]})
PARTS = (MAIN, SURFACE, PRESSURE)
EXTRA_PARTS = (SURFACE, PRESSURE)


def year_chunks(first: int = FIRST_YEAR, last: int = LAST_YEAR, size: int = CHUNK_YEARS):
    return [(y, min(y + size - 1, last)) for y in range(first, last + 1, size)]


def chunk_request(first: int, last: int, part: Part = MAIN) -> FetchSpec:
    """One request: the raw inputs of `part` for every month of `first`..`last`."""
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": [VARIABLES[k].cds_name for k in part.keys],
        "year": [str(y) for y in range(first, last + 1)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "zip",
        **part.extra,
    }
    return FetchSpec(part.name, part.collection, request, part.request_name(first, last))


def _sums_path(work: Path, first: int, last: int, part: Part = MAIN) -> Path:
    return work / "clim" / part.sums_name(first, last)


def _members(path: Path, tmp: str) -> list[Path]:
    """The NetCDF files of a CDS result: the file itself, or the members of its zip."""
    if not zipfile.is_zipfile(path):
        return [path]
    out = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts or "/" in name:
                raise ValueError(f"unsafe member name in archive: {name!r}")
            if name.endswith(".nc"):
                out.append(Path(zf.extract(info, tmp)))
    return out


def monthly_sums(path: Path, part: Part = MAIN) -> xr.Dataset:
    """A downloaded chunk -> per-calendar-month sums and counts of the converted, regridded
    fields: variables (month, latitude, longitude) and `count` (month)."""
    keys = part.keys
    # Extract next to the download: a chunk is ~1 GB, too big for a RAM-backed /tmp.
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        datasets = [xr.open_dataset(p) for p in _members(path, tmp)]
        try:
            fields = {}
            for ds in datasets:
                for var, da in ds.data_vars.items():
                    if "valid_time" in da.dims:
                        if "pressure_level" in da.dims:  # one level was requested
                            da = da.isel(pressure_level=0)
                        fields[NC_TO_KEY.get(str(var), str(var))] = da
            missing = set(keys) - set(fields)
            if missing:
                raise ValueError(f"{path.name} lacks {sorted(missing)}")
            # Accumulated fields are stamped 06:00 on the 1st (the end of the first step),
            # instantaneous ones 00:00, so fields are matched by year and month.
            months = {
                k: [str(m) for m in np.datetime_as_string(fields[k]["valid_time"].values, "M")]
                for k in keys
            }
            order = months[keys[0]]
            if any(v != order for v in months.values()):
                raise ValueError(f"{path.name}: variables cover different months")
            sums: dict[str, np.ndarray] = {}
            count = np.zeros(12, dtype="int64")
            for i, month in enumerate(order):
                raw = {}
                for k in keys:
                    da = fields[k].isel(valid_time=i)
                    da = da.drop_vars([c for c in da.coords if c not in ("latitude", "longitude")])
                    raw[k] = da.astype("float64").load()
                tidy = tidy_dataset(raw, month)
                m = int(month[5:7]) - 1
                for name, da in tidy.data_vars.items():
                    sums.setdefault(str(name), np.zeros((12, 360, 720)))[m] += da.values
                count[m] += 1
        finally:
            for ds in datasets:
                ds.close()
    coords = {"month": np.arange(1, 13), "latitude": tidy.latitude, "longitude": tidy.longitude}
    out = xr.Dataset(
        {k: (("month", "latitude", "longitude"), v) for k, v in sums.items()}, coords=coords
    )
    out["count"] = ("month", count)
    return out


def _load_state(path: Path) -> dict[str, str]:
    return json.loads(path.read_text()) if path.is_file() else {}


def _save_state(path: Path, state: dict[str, str]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(tmp, path)


def _part_of(name: str) -> tuple[Part, int, int]:
    """The part and years a pending request's file name stands for."""
    stem = name.removesuffix(".zip").removeprefix("clim_")
    for part in EXTRA_PARTS:
        if stem.startswith(part.name + "_"):
            first, last = (int(x) for x in stem.removeprefix(part.name + "_").split("_"))
            return part, first, last
    first, last = (int(x) for x in stem.split("_"))
    return MAIN, first, last


def fetch_chunks(
    c, raw: Path, work: Path, max_queued: int = MAX_QUEUED, parts: tuple[Part, ...] = PARTS
) -> list[str]:
    """Collect finished chunk requests (reduce them to monthly sums, delete the download) and
    queue chunks still missing. At most `max_queued` are queued per dataset: the CDS rejects
    more. Returns those still pending."""
    folder = raw / "clim"
    folder.mkdir(parents=True, exist_ok=True)
    (work / "clim").mkdir(parents=True, exist_ok=True)
    state_path = folder / "pending.json"
    state = _load_state(state_path)
    for name, rid in list(state.items()):
        st = c.get_remote(rid).status
        if st == "successful":
            target = folder / name
            if not target.is_file():  # a download that wasn't reduced yet is reused
                part_file = target.with_name(target.name + ".part")
                c.get_remote(rid).download(str(part_file))
                os.replace(part_file, target)
            part, first, last = _part_of(name)
            sums = monthly_sums(target, part)
            out = _sums_path(work, first, last, part)
            encoding = {str(k): {"zlib": True, "complevel": 3} for k in sums.data_vars}
            sums.to_netcdf(out.with_name(out.name + ".part"), encoding=encoding)
            os.replace(out.with_name(out.name + ".part"), out)
            target.unlink()
            del state[name]
        elif st in _FAILED:
            del state[name]
        _save_state(state_path, state)

    def queued(collection: str) -> int:
        return sum(1 for n in state if _part_of(n)[0].collection == collection)

    for part in parts:  # the main part first: it is the one the anomalies wait for
        for first, last in year_chunks():
            spec = chunk_request(first, last, part)
            if queued(part.collection) >= max_queued:
                break
            if spec.filename in state or _sums_path(work, first, last, part).is_file():
                continue
            state[spec.filename] = submit(c, spec)
            _save_state(state_path, state)
    _save_state(state_path, state)
    return sorted(state)


def chunks_done(work: Path, parts: tuple[Part, ...] = PARTS) -> bool:
    return all(_sums_path(work, a, b, part).is_file() for part in parts for a, b in year_chunks())


def parts_done(work: Path) -> tuple[Part, ...]:
    """The parts whose chunks have all arrived."""
    return tuple(p for p in PARTS if chunks_done(work, (p,)))


def _part_means(work: Path, part: Part) -> xr.Dataset:
    total = None
    for a, b in year_chunks():
        with xr.open_dataset(_sums_path(work, a, b, part)) as ds:
            ds = ds.load()
        total = ds if total is None else total + ds
    assert total is not None
    if not (total["count"].values == LAST_YEAR - FIRST_YEAR + 1).all():
        raise ValueError(
            f"expected {LAST_YEAR - FIRST_YEAR + 1} years per month, got {total['count'].values}"
        )
    return (total / total["count"]).drop_vars("count")


def monthly_means(work: Path, parts: tuple[Part, ...] | None = None) -> xr.Dataset:
    """Average all chunks' sums: the 1991-2020 mean of every converted field, per month. The
    parts are merged by key; by default every part that has fully arrived is used (the main
    part is required)."""
    parts = parts if parts is not None else parts_done(work)
    if MAIN not in parts:
        raise FileNotFoundError("the main climatology chunks have not all arrived")
    means = [_part_means(work, p) for p in parts]
    merged = xr.merge(means, compat="no_conflicts")
    return merged


MONTH_DAYS = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])  # leap years incl.


def annual_mean(means: xr.Dataset) -> xr.Dataset:
    """The mean of the 12 monthly means of every field, weighted by days in the month. The
    layer formulas are applied to this, not averaged over 12 derived maps: that is how the
    theory is formulated (proposal F2)."""
    w = xr.DataArray(MONTH_DAYS / MONTH_DAYS.sum(), dims="month", coords={"month": means.month})
    return (means * w).sum("month")


def frame_layers(month: xr.Dataset) -> dict:
    """Every layer's formula applied to one frame's mean inputs (a month, or the annual
    mean), vector layers included. Without winds the wind layers are zero and not published."""
    fields = month.copy()
    for k in _WIND_KEYS:  # the formulas need winds
        if k not in fields:
            fields[k] = xr.zeros_like(month["tsr"])
    return compute_layers(fields)


def climatology_layers(month: xr.Dataset) -> dict:
    """The non-vector layers of `frame_layers`, the ones that have anomalies."""
    return {k: v for k, v in frame_layers(month).items() if k in CLIM_LAYERS}


# ---- publishing the climatology and daily anomalies -----------------------------------

CLIM_INDEX = "clim/clim.json"
PERIOD = f"{FIRST_YEAR}-{LAST_YEAR}"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def build_climatology(work: Path, out: Path) -> int:
    """Publish the climatology: `clim/{MM}/{layer}.png` per month and layer (the layer's own
    packing), `clim/year/{layer}.png` for the annual-mean frame, `clim/series/{layer}/{tx}_{ty}.bin`
    (12 months x 20 x 20 codes, month-major, for the readout chart),
    `clim/year/series/{layer}/{tx}_{ty}.bin` (the annual value, 20 x 20 codes: kept apart so
    the 12-month series files keep their length) and, last, `clim/clim.json`. Layers that
    need a part that hasn't arrived (`net_sfc` needs `str`) are left out. Returns the number
    of files."""
    from .encode import quantise, scalar_png
    from .layers import LAYERS
    from .points import _tiles

    means = monthly_means(work)
    frames = {f"{m + 1:02d}": means.isel(month=m) for m in range(12)}
    frames["year"] = annual_mean(means)
    built: dict[str, dict[str, np.ndarray]] = {}  # layer -> frame -> codes
    radiative = {}
    for frame, inputs in frames.items():
        asr, t_r = radiative_summary(inputs["tsr"].values)
        radiative[frame] = {"asr": round(asr, 2), "t_r": round(t_r, 2)}
    written = 0
    flux_speeds = []
    mean_flow = [k for k in ("wind10", "wind100", "jet250") if f"u{WIND_KEY[k]}" in means]
    for frame, inputs in frames.items():
        layers = frame_layers(inputs)
        written += _frame_products(out, frame, layers, inputs, mean_flow, frame == "year")
        flux_speeds.append(layers["flux_e"].values.values.ravel())
        for lid, field in layers.items():
            if lid not in CLIM_LAYERS:
                continue
            spec = LAYERS[lid]
            c, _ = quantise(
                field.values.values, field.masked.values, *spec.encode, log=spec.log,
                step=spec.resolution,
            )  # fmt: skip
            built.setdefault(lid, {})[frame] = c
            _write(out / "clim" / frame / f"{lid}.png", scalar_png(c))
            written += 1
    for lid, by_frame in built.items():
        months = np.stack([by_frame[f"{m + 1:02d}"] for m in range(12)])
        for (tx, ty), tile in _tiles(months):
            _write(out / "clim" / "series" / lid / f"{tx}_{ty}.bin", tile.tobytes())
            written += 1
        for (tx, ty), tile in _tiles(by_frame["year"][None]):
            _write(out / "clim" / "year" / "series" / lid / f"{tx}_{ty}.bin", tile.tobytes())
            written += 1
    index = {
        "period": PERIOD,
        "layers": [lid for lid in CLIM_LAYERS if lid in built],
        "frames": [*frames],
        "radiative": radiative,  # <ASR_TOA> and T_r of each frame, for the panels and readout
        "file": "clim/{MM}/{layer}.png",
        "series": "clim/series/{layer}/{tx}_{ty}.bin",
        "year_file": "clim/year/{layer}.png",
        "year_series": "clim/year/series/{layer}/{tx}_{ty}.bin",
        # climate point chunks (same layout as the daily ones), zonal budgets, and the
        # divergent energy flux and 1991-2020 mean wind vectors of each frame
        "points": "clim/points/{frame}/{tx}_{ty}.bin",
        "zonal": "clim/zonal/{frame}.json",
        "uv_file": "clim/{frame}/{layer}_uv.png",
        "uv_layers": ["flux_e", *mean_flow],
        # one arrow reference for all 13 frames: the 98th percentile of |F|, so lengths compare
        "flux_ref": float(np.percentile(np.concatenate(flux_speeds), 98)),
    }
    _write(out / CLIM_INDEX, json.dumps(index, indent=1).encode())
    return written + 1


WIND_KEY = {"wind10": "10", "wind100": "100", "jet250": "250"}


def _frame_products(out, frame, layers, inputs, mean_flow, is_year) -> int:
    """One frame's vector files (`flux_e_uv.png`, the mean-flow winds), climate point chunk
    and zonal budget. The speed of the mean wind is far below the mean of daily speeds, so
    the wind layers are published as vectors for particles only, never as speed rasters or
    point values. `flux_e` is linear in `div_e`, so its climatology is honest."""
    from . import zonal
    from .derived import compute_extras
    from .publish import encode_date

    vectors, _, _ = encode_date({k: layers[k] for k in ("flux_e", *mean_flow)})
    files, _, points = encode_date(
        {k: v for k, v in layers.items() if k not in WIND_KEY}, compute_extras(inputs)
    )
    written = 0
    for name, data in vectors.items():
        if name.endswith("_uv.png"):
            _write(out / "clim" / frame / name, data)
            written += 1
    for name, data in points.items():
        _write(out / "clim" / "points" / frame / name, data)
        written += 1
    lw_up = inputs["lw_up"].values if "lw_up" in inputs else None
    summary = zonal.zonal_summary(
        zonal.layer_inputs(layers, inputs["skt"].values, lw_up), year=is_year
    )
    if is_year and "net_sfc" in layers:
        summary["budget_residual"] = zonal.budget_residual(
            layers["net_toa"].values.values,
            inputs["p86.162"].values.astype("float64"),
            layers["net_sfc"].values.values,
        )
    _write(out / "clim" / "zonal" / f"{frame}.json", zonal.to_json(summary))
    return written + 1


def read_index(out: Path) -> dict | None:
    path = out / CLIM_INDEX
    return json.loads(path.read_text()) if path.is_file() else None


class Climatology:
    """The published climatology, read back from its PNGs for computing anomalies."""

    def __init__(self, out: Path):
        self.out = out
        self.index = read_index(out)
        self._cache: dict[tuple[int, str], tuple[np.ndarray, np.ndarray]] = {}

    @property
    def available(self) -> bool:
        return self.index is not None

    def get(self, month: int, lid: str) -> tuple[np.ndarray, np.ndarray]:
        """(values, masked) of one layer's mean for a calendar month (1-12)."""
        from .encode import MASKED, decode, png_to_ints
        from .layers import LAYERS

        key = (month, lid)
        if key not in self._cache:
            spec = LAYERS[lid]
            codes = png_to_ints((self.out / "clim" / f"{month:02d}" / f"{lid}.png").read_bytes())
            values = decode(codes, *spec.encode, log=spec.log, step=spec.resolution)
            self._cache[key] = (values, codes == MASKED)
        return self._cache[key]


def anomaly_codes(values, masked, clim_values, clim_masked, lid: str) -> tuple[np.ndarray, int]:
    """Daily value minus the climatology, packed with the layer's anomaly encoding. Masked
    where either is masked; no data where either is missing."""
    from .encode import quantise
    from .layers import LAYERS

    spec = LAYERS[lid]
    anom = np.asarray(values, dtype="float64") - clim_values
    return quantise(
        anom, np.asarray(masked) | clim_masked, *spec.anomaly_encode, step=spec.anomaly_resolution
    )


def encode_anomalies(
    layers: dict, month: int, climatology: Climatology
) -> tuple[dict[str, bytes], dict[str, int]]:
    """{`{layer}_anom.png`: bytes} for every layer with a climatology, and clipped counts."""
    from .encode import scalar_png

    files: dict[str, bytes] = {}
    clipped: dict[str, int] = {}
    have = (climatology.index or {}).get("layers", CLIM_LAYERS)
    for lid in CLIM_LAYERS:
        if lid not in layers or lid not in have:  # not built, or no climatology for it yet
            continue
        cv, cm = climatology.get(month, lid)
        codes, n = anomaly_codes(layers[lid].values.values, layers[lid].masked.values, cv, cm, lid)
        files[f"{lid}_anom.png"] = scalar_png(codes)
        clipped[lid] = n
    return files, clipped
