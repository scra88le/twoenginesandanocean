"""Write the front end's test fixtures with the real pipeline encoder.

    python pipeline/scripts/make_web_fixtures.py

- web/tests/fixtures/scalar.png: code(row j, col i) = (j * 720 + i) % 65536
- web/tests/fixtures/vector.png: u = (i * 91 + j) % 65536, v = (i % 256) << 8, so the
  low byte of v, and with it the alpha channel, is 0 everywhere
- web/e2e/fixtures/data: a data root with a manifest and three layers for three dates.
  t_emit = 200 + 0.1 * i K on the newest date and 5 K less for each day before (depends on
  longitude only); net_toa = latitude in W m-2; carnot = 15% in the north and 0 (clamped,
  hatched) in the south.
"""

from pathlib import Path

import numpy as np

from pipeline.encode import quantise, scalar_png, vector_png
from pipeline.layers import LAYERS
from pipeline.publish import publish_date

ROOT = Path(__file__).resolve().parents[2]
E2E_DATES = ["2026-09-29", "2026-09-30", "2026-10-01"]
j, i = np.mgrid[0:360, 0:720]


def unit_fixtures() -> None:
    out = ROOT / "web/tests/fixtures"
    out.mkdir(parents=True, exist_ok=True)
    (out / "scalar.png").write_bytes(scalar_png(((j * 720 + i) % 65536).astype(np.uint16)))
    u = ((i * 91 + j) % 65536).astype(np.uint16)
    v = ((i % 256) << 8).astype(np.uint16)
    (out / "vector.png").write_bytes(vector_png(u, v))


def e2e_fixtures() -> None:
    lat = 89.75 - 0.5 * j
    data = ROOT / "web/e2e/fixtures/data"
    for k, day in enumerate(E2E_DATES):
        older = len(E2E_DATES) - 1 - k  # 0 for the newest date
        fields = {
            "t_emit": 200 + 0.1 * i - 5.0 * older,
            "net_toa": lat,
            "carnot": np.where(lat > 0, 15.0, 0.0),
        }
        files = {}
        for lid, x in fields.items():
            s = LAYERS[lid]
            codes, _ = quantise(x, np.zeros_like(x, bool), *s.encode, log=s.log, step=s.resolution)
            files[f"{lid}.png"] = scalar_png(codes)
        publish_date(data, day, files, built_at="2026-10-18T00:00:00Z")


if __name__ == "__main__":
    unit_fixtures()
    e2e_fixtures()
    for p in sorted(
        [*(ROOT / "web/tests/fixtures").rglob("*.*"), *(ROOT / "web/e2e/fixtures").rglob("*.*")]
    ):
        print(p.relative_to(ROOT), p.stat().st_size, "bytes")
