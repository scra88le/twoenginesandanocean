"""Suggest fixed anomaly display ranges from the published anomaly maps.

    python pipeline/scripts/anomaly_ranges.py out

For each layer with an anomaly, decodes `{layer}_anom.png` on every published date, takes
the 98th percentile of |anomaly| over all valid cells (area-weighted) and rounds it up to
1, 2, 2.5 or 5 times a power of ten. Prints the ranges and how much of the area each one
clips, for `ANOMALY_DISPLAY` in pipeline/src/pipeline/layers.py.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

from pipeline.encode import decode, png_to_ints
from pipeline.layers import ANOMALY, LAYERS

STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)


def nice_ceiling(x: float) -> float:
    if x <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(x))
    return next(s * p for s in STEPS if s * p >= x * (1 - 1e-9))


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    cum = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cum, q * cum[-1])])


def main(out: Path) -> None:
    dates = json.loads((out / "manifest.json").read_text())["dates"]
    w_row = np.cos(np.deg2rad(89.75 - 0.5 * np.arange(360)))[:, None] * np.ones((1, 720))
    ranges = {}
    for lid in ANOMALY:
        s = LAYERS[lid]
        vals, wts = [], []
        for d in dates:
            p = out / "fields" / d / f"{lid}_anom.png"
            if not p.is_file():
                continue
            a = decode(png_to_ints(p.read_bytes()), *s.anomaly_encode, step=s.anomaly_resolution)
            ok = np.isfinite(a)
            vals.append(np.abs(a[ok]))
            wts.append(w_row[ok])
        if not vals:
            print(f"{lid}: no anomaly maps")
            continue
        v, w = np.concatenate(vals), np.concatenate(wts)
        p98 = weighted_quantile(v, w, 0.98)
        shown = min(nice_ceiling(p98), s.anomaly_encode[1])
        clipped = 100 * float(w[v > shown].sum() / w.sum())
        ranges[lid] = shown
        print(f"{lid:10s} p98 {p98:10.4g}  ->  ±{shown:<8g} ({clipped:.1f}% of area beyond)")
    print("ANOMALY_DISPLAY =", {k: (int(x) if x == int(x) else x) for k, x in ranges.items()})


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "out"))
