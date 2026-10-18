"""Encode a date's layers and publish them to the storage layout, manifest last.

A failed run must leave the published site working: a date's files are written into a
temporary directory and swapped in only once all of them are written, and the manifest,
which is what the front end reads first, is replaced atomically at the very end.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from .derived import LayerField
from .encode import FIRST_VALID, MASKED, NODATA, quantise, scalar_png, scale_offset, vector_png
from .layers import GROUPS, LAYERS, LayerSpec

MANIFEST_VERSION = 1
KEEP_DAYS = 90


def encode_date(layers: dict[str, LayerField]) -> tuple[dict[str, bytes], dict[str, dict]]:
    """Layer fields -> ({filename: PNG bytes}, {layer: stats})."""
    files: dict[str, bytes] = {}
    stats: dict[str, dict] = {}
    for lid, field in layers.items():
        spec = LAYERS[lid]
        masked = field.masked.values
        codes, clipped = quantise(
            field.values.values, masked, *spec.encode, log=spec.log, step=spec.resolution
        )
        files[f"{lid}.png"] = scalar_png(codes)
        if spec.uv_encode is not None:
            u, cu = quantise(field.u.values, masked, *spec.uv_encode, step=spec.uv_resolution)
            v, cv = quantise(field.v.values, masked, *spec.uv_encode, step=spec.uv_resolution)
            files[f"{lid}_uv.png"] = vector_png(u, v)
            clipped += cu + cv
        stats[lid] = {
            "nodata_pct": float(100 * np.mean(codes == NODATA)),
            "masked_pct": float(100 * np.mean(codes == MASKED)),
            "clipped": clipped,
        }
    return files, stats


def _range(lo: float, hi: float, step: float, log: bool = False) -> dict:
    scale, offset = scale_offset(lo, hi, log, step)
    return {"lo": lo, "hi": hi, "log": log, "scale": scale, "offset": offset}


def _layer_meta(s: LayerSpec) -> dict:
    return {
        "title": s.title,
        "group": s.group,
        "group_name": GROUPS[s.group],
        "units": s.units,
        "colour": s.colour,
        "display": list(s.display) if s.display is not None else "auto",
        "log": s.log,
        "centre": s.centre,
        "vector": s.uv_encode is not None,
        "anomaly": s.anomaly,
        "encode": _range(*s.encode, s.resolution, log=s.log),
        "uv_encode": _range(*s.uv_encode, s.uv_resolution) if s.uv_encode else None,
        "anomaly_encode": (
            _range(*s.anomaly_encode, s.anomaly_resolution) if s.anomaly_encode else None
        ),
    }


def _credits(year: int) -> str:
    return (
        f"Generated using Copernicus Climate Change Service information [{year}]: ERA5 "
        "(Hersbach et al., 2020), via the Copernicus Climate Data Store. Neither the European "
        "Commission nor ECMWF is responsible for any use that may be made of the Copernicus "
        "information or data it contains."
    )


def build_manifest(dates: list[str], built_at: str) -> dict:
    return {
        "version": MANIFEST_VERSION,
        "built_at": built_at,
        "dates": dates,
        "grid": {"nlon": 720, "nlat": 360, "lon0": -179.75, "lat0": 89.75, "step": 0.5},
        "codes": {"nodata": NODATA, "masked": MASKED, "first_valid": FIRST_VALID},
        "files": {"field": "fields/{date}/{layer}.png", "uv": "fields/{date}/{layer}_uv.png"},
        "layers": {lid: _layer_meta(s) for lid, s in LAYERS.items()},
        "credits": _credits(int(built_at[:4])),
    }


def _write_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _write_manifest(out: Path, manifest: dict) -> None:
    tmp = out / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=1))
    os.replace(tmp, out / "manifest.json")


def _read_dates(out: Path) -> list[str]:
    path = out / "manifest.json"
    return json.loads(path.read_text())["dates"] if path.is_file() else []


def publish_date(
    out: Path,
    day: str,
    files: dict[str, bytes],
    built_at: str | None = None,
    keep_days: int = KEEP_DAYS,
) -> None:
    """Write one date's files, then the manifest, then delete dates beyond `keep_days`."""
    day = date.fromisoformat(day).isoformat()  # also rejects anything path-like
    built_at = built_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = out / "fields"
    fields.mkdir(parents=True, exist_ok=True)

    tmp = fields / f".{day}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        for name, data in files.items():
            _write_file(tmp / name, data)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    final = fields / day
    if final.exists():
        old = fields / f".{day}.old"
        shutil.rmtree(old, ignore_errors=True)
        os.rename(final, old)
        os.rename(tmp, final)
        shutil.rmtree(old)
    else:
        os.rename(tmp, final)

    previous = _read_dates(out)
    dates = sorted(set(previous) | {day})[-keep_days:]
    _write_manifest(out, build_manifest(dates, built_at))
    for gone in set(previous) - set(dates):
        shutil.rmtree(fields / gone, ignore_errors=True)
