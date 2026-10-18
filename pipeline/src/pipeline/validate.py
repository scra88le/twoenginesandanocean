"""Per-date validation: a date that fails is logged and not published."""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

import numpy as np
import xarray as xr

from .convert import area_weighted_mean
from .derived import SECONDS_PER_DAY, LayerField
from .layers import NATURAL

# Area-weighted global means (spec, "Validation (per date)").
RANGES = {"tsr": (220.0, 260.0), "olr": (225.0, 255.0), "tp_mm_day": (2.5, 3.5)}
MAX_NODATA_PCT = 1.0
CARNOT_RANGE = (0.0, 40.0)  # %, after clamping
LOG_FIELDS = ["date", "tsr", "olr", "tp_mm_day", "status", "problems"]


def global_means(tidy: xr.Dataset) -> dict[str, float]:
    return {
        "tsr": area_weighted_mean(tidy["tsr"]),
        "olr": area_weighted_mean(tidy["olr"]),
        "tp_mm_day": area_weighted_mean(tidy["tp"]) * SECONDS_PER_DAY,
    }


def check(tidy: xr.Dataset, layers: dict[str, LayerField], stats: dict[str, dict]) -> list[str]:
    """Problems with one date; an empty list means it can be published."""
    problems = []
    for name, value in global_means(tidy).items():
        lo, hi = RANGES[name]
        if not lo <= value <= hi:
            problems.append(f"global mean {name} {value:.2f} outside {lo:g}-{hi:g}")
    for lid in NATURAL:
        if lid in stats and stats[lid]["nodata_pct"] > MAX_NODATA_PCT:
            problems.append(
                f"{lid}: {stats[lid]['nodata_pct']:.2f}% no data (max {MAX_NODATA_PCT:g}%)"
            )
    if "carnot" in layers:
        eta = layers["carnot"].values.values
        lo, hi = float(np.nanmin(eta)), float(np.nanmax(eta))
        if lo < CARNOT_RANGE[0] or hi > CARNOT_RANGE[1]:
            problems.append(
                f"carnot {lo:.1f}-{hi:.1f}% outside {CARNOT_RANGE[0]:g}-{CARNOT_RANGE[1]:g}%"
            )
    return problems


def write_log(out: Path, day: str, means: dict[str, float], problems: list[str]) -> None:
    """Record a date's global means in logs/global_means.csv: one row per date, sorted."""
    path = out / "logs" / "global_means.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = {}
    if path.is_file():
        rows = {r["date"]: r for r in csv.DictReader(path.open())}
    rows[day] = {
        "date": day,
        **{k: f"{means[k]:.3f}" for k in ("tsr", "olr", "tp_mm_day")},
        "status": "failed" if problems else "ok",
        "problems": "; ".join(problems),
    }
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LOG_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows[d] for d in sorted(rows))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(buf.getvalue())
    os.replace(tmp, path)
