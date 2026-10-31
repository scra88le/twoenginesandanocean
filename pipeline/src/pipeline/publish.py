"""Encode a date's layers and publish them to the storage layout, manifest last.

A failed run must leave the published site working: a date's files are written into a
temporary directory and swapped in only once all of them are written, and the manifest,
which is what the front end reads first, is replaced atomically at the very end.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from .derived import LayerField
from .encode import FIRST_VALID, MASKED, NODATA, quantise, scalar_png, scale_offset, vector_png
from .info import INFO
from .layers import EXTRAS, GROUP_BLURBS, GROUPS, LAYERS, LayerSpec
from .points import POINT_FIELDS, TILE, point_tiles

MANIFEST_VERSION = 1
KEEP_DAYS = 90


def encode_date(
    layers: dict[str, LayerField], extras: dict[str, LayerField] | None = None
) -> tuple[dict[str, bytes], dict[str, dict], dict[str, bytes]]:
    """Layer fields (and readout extras) -> ({PNG filename: bytes}, {layer: stats},
    {point tile filename: bytes})."""
    files: dict[str, bytes] = {}
    stats: dict[str, dict] = {}
    point_codes: dict[str, np.ndarray] = {}
    for eid, field in (extras or {}).items():
        spec = EXTRAS[eid]
        point_codes[eid], _ = quantise(
            field.values.values, field.masked.values, *spec.encode, step=spec.resolution
        )
    for lid, field in layers.items():
        spec = LAYERS[lid]
        masked = field.masked.values
        codes, clipped = quantise(
            field.values.values, masked, *spec.encode, log=spec.log, step=spec.resolution
        )
        point_codes[lid] = codes
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
    return files, stats, point_tiles(point_codes)


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
        "anomaly": s.anomaly_encode is not None,
        "anomaly_display": list(s.anomaly_display) if s.anomaly_display else None,
        "anomaly_colour": s.anomaly_colour if s.anomaly_encode else None,
        "encode": _range(*s.encode, s.resolution, log=s.log),
        "uv_encode": _range(*s.uv_encode, s.uv_resolution) if s.uv_encode else None,
        "anomaly_encode": (
            _range(*s.anomaly_encode, s.anomaly_resolution) if s.anomaly_encode else None
        ),
        "hatch_zero": s.hatch_zero,
        "modes": list(s.modes),
        "default_mode": s.default_mode,
        "advanced": s.advanced,
        "menu_order": s.menu_order,
        "info": asdict(INFO[s.id]),
    }


def _credits(year: int) -> str:
    return (
        f"Generated using Copernicus Climate Change Service information [{year}]: ERA5 "
        "(Hersbach et al., 2020), via the Copernicus Climate Data Store. Neither the European "
        "Commission nor ECMWF is responsible for any use that may be made of the Copernicus "
        "information or data it contains."
    )


def build_manifest(
    dates: list[str],
    built_at: str,
    built_layers: list[str] | None = None,
    clim: dict | None = None,
    radiative: dict[str, dict[str, float]] | None = None,
    ocean: dict | None = None,
) -> dict:
    manifest = {
        "version": MANIFEST_VERSION,
        "built_at": built_at,
        "dates": dates,
        "built_layers": built_layers or [],
        "grid": {"nlon": 720, "nlat": 360, "lon0": -179.75, "lat0": 89.75, "step": 0.5},
        "codes": {"nodata": NODATA, "masked": MASKED, "first_valid": FIRST_VALID},
        "files": {
            "field": "fields/{date}/{layer}.png",
            "uv": "fields/{date}/{layer}_uv.png",
            "anomaly": "fields/{date}/{layer}_anom.png",
        },
        "clim": clim,  # null until the climatology job has run
        # <ASR_TOA> (W m-2) and the radiative temperature T_r (K) of each published date: the
        # cold side of `carnot` and `g_max`. The climate frames' are in `clim.radiative`.
        "radiative": radiative or {},
        "groups": {str(g): {"name": GROUPS[g], "blurb": GROUP_BLURBS[g]} for g in GROUPS},
        "layers": {lid: _layer_meta(s) for lid, s in LAYERS.items()},
        "points": {
            "file": "points/{date}/{tx}_{ty}.bin",
            "tile": TILE,
            "fields": list(POINT_FIELDS),
            "extras": {
                e.id: {
                    "title": e.title,
                    "units": e.units,
                    "encode": _range(*e.encode, e.resolution),
                }
                for e in EXTRAS.values()
            },
        },
        "series": {"file": "series/{layer}/{tx}_{ty}.bin", "magic": "EHS1"},
        "credits": _credits(int(built_at[:4])),
    }
    if ocean:  # the ocean overlay's block, written by `pipeline.ocean` and carried forward
        manifest["ocean"] = ocean
    return manifest


def _write_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _write_manifest(out: Path, manifest: dict) -> None:
    tmp = out / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=1))
    os.replace(tmp, out / "manifest.json")


def _read_manifest(out: Path) -> dict:
    path = out / "manifest.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _clim_index(out: Path) -> dict | None:
    path = out / "clim" / "clim.json"
    return json.loads(path.read_text()) if path.is_file() else None


def refresh_manifest(out: Path, built_at: str | None = None) -> None:
    """Rewrite the manifest for the dates already published (after the climatology job, or
    when layer metadata changes)."""
    old = _read_manifest(out)
    built_at = built_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_manifest(
        out,
        build_manifest(
            old.get("dates", []),
            built_at,
            old.get("built_layers", []),
            _clim_index(out),
            old.get("radiative", {}),
            old.get("ocean"),
        ),
    )


def _layer_ids(files: dict[str, bytes]) -> set[str]:
    """Layer IDs with a field PNG among `files` (not the _uv companions)."""
    stems = {name.removesuffix(".png") for name in files if name.endswith(".png")}
    return {s for s in stems if s in LAYERS}


def _swap_in(parent: Path, day: str, files: dict[str, bytes]) -> None:
    """Write `files` into a temporary directory, then swap it in as `parent/day`."""
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{day}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        for name, data in files.items():
            _write_file(tmp / name, data)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    final = parent / day
    if final.exists():
        old = parent / f".{day}.old"
        shutil.rmtree(old, ignore_errors=True)
        os.rename(final, old)
        os.rename(tmp, final)
        shutil.rmtree(old)
    else:
        os.rename(tmp, final)


def publish_date(
    out: Path,
    day: str,
    files: dict[str, bytes],
    built_at: str | None = None,
    keep_days: int = KEEP_DAYS,
    points: dict[str, bytes] | None = None,
    radiative: dict[str, float] | None = None,
    zonal: bytes | None = None,
) -> None:
    """Write one date's point chunks and map files, then the manifest, then delete dates
    beyond `keep_days`. `radiative` is the date's {"asr", "t_r"} for the manifest; `zonal`
    is the date's `zonal/{date}.json`."""
    day = date.fromisoformat(day).isoformat()  # also rejects anything path-like
    built_at = built_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = out / "fields"
    if points:
        _swap_in(out / "points", day, points)
    if zonal is not None:
        (out / "zonal").mkdir(exist_ok=True)
        _write_file(out / "zonal" / f"{day}.json", zonal)
    _swap_in(fields, day, files)

    old = _read_manifest(out)
    previous = old.get("dates", [])
    dates = sorted(set(previous) | {day})[-keep_days:]
    built = sorted(set(old.get("built_layers", [])) | _layer_ids(files))
    kept = {d: v for d, v in old.get("radiative", {}).items() if d in dates}
    if radiative is not None:
        kept[day] = radiative
    ocean = old.get("ocean")
    if ocean:
        ocean = {**ocean, "dates": {k: v for k, v in ocean["dates"].items() if k in dates}}
    _write_manifest(out, build_manifest(dates, built_at, built, _clim_index(out), kept, ocean))
    for gone in set(previous) - set(dates):
        shutil.rmtree(fields / gone, ignore_errors=True)
        shutil.rmtree(out / "ocean" / gone, ignore_errors=True)
        shutil.rmtree(out / "points" / gone, ignore_errors=True)
        (out / "zonal" / f"{gone}.json").unlink(missing_ok=True)
