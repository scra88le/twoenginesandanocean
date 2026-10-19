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
from pathlib import Path

import numpy as np
import xarray as xr

from .convert import tidy_dataset
from .derived import compute_layers
from .fetch import _FAILED, VARIABLES, FetchSpec, submit
from .layers import ANOMALY
from .load import NC_TO_KEY

MONTHLY = "reanalysis-era5-single-levels-monthly-means"
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


def year_chunks(first: int = FIRST_YEAR, last: int = LAST_YEAR, size: int = CHUNK_YEARS):
    return [(y, min(y + size - 1, last)) for y in range(first, last + 1, size)]


def chunk_request(first: int, last: int) -> FetchSpec:
    """One request: the raw inputs for every month of `first`..`last`."""
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": [VARIABLES[k].cds_name for k in CLIM_KEYS],
        "year": [str(y) for y in range(first, last + 1)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "zip",
    }
    return FetchSpec("monthly", MONTHLY, request, f"clim_{first}_{last}.zip")


def _sums_path(work: Path, first: int, last: int) -> Path:
    return work / "clim" / f"sums_{first}_{last}.nc"


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


def monthly_sums(path: Path) -> xr.Dataset:
    """A downloaded chunk -> per-calendar-month sums and counts of the converted, regridded
    fields: variables (month, latitude, longitude) and `count` (month)."""
    # Extract next to the download: a chunk is ~1 GB, too big for a RAM-backed /tmp.
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        datasets = [xr.open_dataset(p) for p in _members(path, tmp)]
        try:
            fields = {}
            for ds in datasets:
                for var, da in ds.data_vars.items():
                    if "valid_time" in da.dims:
                        fields[NC_TO_KEY.get(str(var), str(var))] = da
            missing = set(CLIM_KEYS) - set(fields)
            if missing:
                raise ValueError(f"{path.name} lacks {sorted(missing)}")
            # Accumulated fields are stamped 06:00 on the 1st (the end of the first step),
            # instantaneous ones 00:00, so fields are matched by year and month.
            months = {
                k: [str(m) for m in np.datetime_as_string(fields[k]["valid_time"].values, "M")]
                for k in CLIM_KEYS
            }
            order = months["tsr"]
            if any(v != order for v in months.values()):
                raise ValueError(f"{path.name}: variables cover different months")
            sums: dict[str, np.ndarray] = {}
            count = np.zeros(12, dtype="int64")
            for i, month in enumerate(order):
                raw = {}
                for k in CLIM_KEYS:
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


def fetch_chunks(c, raw: Path, work: Path, max_queued: int = MAX_QUEUED) -> list[str]:
    """Collect finished chunk requests (reduce them to monthly sums, delete the download) and
    queue chunks still missing, at most `max_queued` at a time. Returns those still pending."""
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
                part = target.with_name(target.name + ".part")
                c.get_remote(rid).download(str(part))
                os.replace(part, target)
            first, last = (int(x) for x in name.removesuffix(".zip").split("_")[1:])
            sums = monthly_sums(target)
            out = _sums_path(work, first, last)
            encoding = {str(k): {"zlib": True, "complevel": 3} for k in sums.data_vars}
            sums.to_netcdf(out.with_name(out.name + ".part"), encoding=encoding)
            os.replace(out.with_name(out.name + ".part"), out)
            target.unlink()
            del state[name]
        elif st in _FAILED:
            del state[name]
        _save_state(state_path, state)
    for first, last in year_chunks():
        spec = chunk_request(first, last)
        if len(state) >= max_queued:
            break
        if spec.filename in state or _sums_path(work, first, last).is_file():
            continue
        state[spec.filename] = submit(c, spec)
        _save_state(state_path, state)
    _save_state(state_path, state)
    return sorted(state)


def chunks_done(work: Path) -> bool:
    return all(_sums_path(work, a, b).is_file() for a, b in year_chunks())


def monthly_means(work: Path) -> xr.Dataset:
    """Average all chunks' sums: the 1991-2020 mean of every converted field, per month."""
    total = None
    for a, b in year_chunks():
        with xr.open_dataset(_sums_path(work, a, b)) as ds:
            ds = ds.load()
        total = ds if total is None else total + ds
    assert total is not None
    if not (total["count"].values == LAST_YEAR - FIRST_YEAR + 1).all():
        raise ValueError(
            f"expected {LAST_YEAR - FIRST_YEAR + 1} years per month, got {total['count'].values}"
        )
    return (total / total["count"]).drop_vars("count")


def climatology_layers(month: xr.Dataset) -> dict:
    """The layer formulas applied to one month's mean inputs, for the non-vector layers."""
    fields = month.copy()
    for k in _WIND_KEYS:  # the formulas need winds; vector layers are dropped below
        fields[k] = xr.zeros_like(month["tsr"])
    layers = compute_layers(fields)
    return {k: v for k, v in layers.items() if k in CLIM_LAYERS}


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
    packing), `clim/series/{layer}/{tx}_{ty}.bin` (12 months x 20 x 20 codes, month-major,
    for the readout chart) and, last, `clim/clim.json`. Returns the number of files."""
    from .encode import quantise, scalar_png
    from .layers import LAYERS
    from .points import _tiles

    means = monthly_means(work)
    codes: dict[str, np.ndarray] = {
        lid: np.zeros((12, 360, 720), dtype="<u2") for lid in CLIM_LAYERS
    }
    written = 0
    for m in range(12):
        for lid, field in climatology_layers(means.isel(month=m)).items():
            spec = LAYERS[lid]
            c, _ = quantise(
                field.values.values, field.masked.values, *spec.encode, log=spec.log,
                step=spec.resolution,
            )  # fmt: skip
            codes[lid][m] = c
            _write(out / "clim" / f"{m + 1:02d}" / f"{lid}.png", scalar_png(c))
            written += 1
    for lid, stack in codes.items():
        for (tx, ty), tile in _tiles(stack):
            _write(out / "clim" / "series" / lid / f"{tx}_{ty}.bin", tile.tobytes())
            written += 1
    index = {
        "period": PERIOD,
        "layers": list(CLIM_LAYERS),
        "file": "clim/{MM}/{layer}.png",
        "series": "clim/series/{layer}/{tx}_{ty}.bin",
    }
    _write(out / CLIM_INDEX, json.dumps(index, indent=1).encode())
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
    for lid in CLIM_LAYERS:
        if lid not in layers:
            continue
        cv, cm = climatology.get(month, lid)
        codes, n = anomaly_codes(layers[lid].values.values, layers[lid].masked.values, cv, cm, lid)
        files[f"{lid}_anom.png"] = scalar_png(codes)
        clipped[lid] = n
    return files, clipped
