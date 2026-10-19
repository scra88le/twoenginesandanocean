"""Write the front end's test fixtures with the real pipeline encoder.

    python pipeline/scripts/make_web_fixtures.py

- web/tests/fixtures/scalar.png: code(row j, col i) = (j * 720 + i) % 65536
- web/tests/fixtures/vector.png: u = (i * 91 + j) % 65536, v = (i % 256) << 8, so the
  low byte of v, and with it the alpha channel, is 0 everywhere
- web/e2e/fixtures/data: a data root with a manifest and three layers for three dates.
  t_emit = 200 + 0.1 * i K on the newest date and 5 K less for each day before (depends on
  longitude only); net_toa = latitude in W m-2; carnot = 15% in the north and 0 (clamped,
  hatched) in the south. Winds, for the particle layer: wind10 is a uniform 10 m/s westerly
  (u = 10, v = 0) on the two newest dates only, so the oldest date has no wind; jet250 is a
  uniform 30 m/s southerly (u = 0, v = 30) on the newest date; wind100 is a uniform 8 m/s
  easterly (u = -8) and flux_e a uniform 5e8 W m-1 eastward flux, both on the two newest
  dates only. The other layers the guided tour visits (j_ratio, evap_frac, diss_bl, precip,
  div_e) are uniform scalars on every date: 1.0, 0.5, 2 W m-2, 3 mm/day and 0.
  Point chunks hold those layers plus the extras t_skin = 288 K (north) / 300 K (south) and
  j_opt = 100 W m-2 on land (the northern hemisphere) and masked at sea; series chunks are
  rebuilt from the PNGs, so t_emit at a cell steps by 5 K a day. Only the tiles in
  FIXTURE_TILES are kept (around 0.25 E, 35.25 S and 35.25 N), so the fixtures stay small; other
  tiles are missing on purpose. A climatology for t_emit (230 K), net_toa (0) and carnot
  (10%), the same every month, gives anomalies of t_emit - 230 K, the latitude, and +5 / -10.
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from pipeline.climatology import Climatology, encode_anomalies
from pipeline.encode import quantise, scalar_png, vector_png
from pipeline.layers import EXTRAS, LAYERS
from pipeline.points import build_series, point_tiles
from pipeline.publish import publish_date

ROOT = Path(__file__).resolve().parents[2]
E2E_DATES = ["2026-09-29", "2026-09-30", "2026-10-01"]
FIXTURE_TILES = {"18_12.bin", "18_5.bin"}
j, i = np.mgrid[0:360, 0:720]


def unit_fixtures() -> None:
    out = ROOT / "web/tests/fixtures"
    out.mkdir(parents=True, exist_ok=True)
    (out / "scalar.png").write_bytes(scalar_png(((j * 720 + i) % 65536).astype(np.uint16)))
    u = ((i * 91 + j) % 65536).astype(np.uint16)
    v = ((i % 256) << 8).astype(np.uint16)
    (out / "vector.png").write_bytes(vector_png(u, v))


class _Field:
    """Just enough of a LayerField (values and mask) for encode_anomalies."""

    def __init__(self, x: np.ndarray):
        self.values = SimpleNamespace(values=x)
        self.masked = SimpleNamespace(values=np.zeros_like(x, bool))


def _codes(lid: str, x: np.ndarray) -> np.ndarray:
    s = LAYERS[lid]
    return quantise(x, np.zeros_like(x, bool), *s.encode, log=s.log, step=s.resolution)[0]


def _uv_codes(lid: str, x: np.ndarray) -> np.ndarray:
    s = LAYERS[lid]
    return quantise(x, np.zeros_like(x, bool), *s.uv_encode, step=s.uv_resolution)[0]


CLIM = {"t_emit": 230.0, "net_toa": 0.0, "carnot": 10.0}


def clim_fixtures(data: Path) -> None:
    import json

    from pipeline.points import _tiles

    for lid, value in CLIM.items():
        codes = _codes(lid, np.full((360, 720), value))
        for m in range(1, 13):
            path = data / "clim" / f"{m:02d}" / f"{lid}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(scalar_png(codes))
        stack = np.repeat(codes[None], 12, 0).astype("<u2")
        for (tx, ty), tile in _tiles(stack):
            if f"{tx}_{ty}.bin" in FIXTURE_TILES:
                path = data / "clim" / "series" / lid / f"{tx}_{ty}.bin"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(tile.tobytes())
    index = {
        "period": "1991-2020",
        "layers": list(CLIM),
        "file": "clim/{MM}/{layer}.png",
        "series": "clim/series/{layer}/{tx}_{ty}.bin",
    }
    (data / "clim" / "clim.json").write_text(json.dumps(index, indent=1))


def e2e_fixtures() -> None:
    lat = 89.75 - 0.5 * j
    data = ROOT / "web/e2e/fixtures/data"
    clim_fixtures(data)
    climatology = Climatology(data)
    for k, day in enumerate(E2E_DATES):
        older = len(E2E_DATES) - 1 - k  # 0 for the newest date
        fields = {
            "t_emit": 200 + 0.1 * i - 5.0 * older,
            "net_toa": lat,
            "carnot": np.where(lat > 0, 15.0, 0.0),
            "j_ratio": np.full_like(lat, 1.0),
            "evap_frac": np.full_like(lat, 0.5),
            "diss_bl": np.full_like(lat, 2.0),
            "precip": np.full_like(lat, 3.0),
            "div_e": np.zeros_like(lat),
        }
        winds = (
            {"wind10": (10.0, 0.0), "wind100": (-8.0, 0.0), "flux_e": (5e8, 0.0)}
            if older <= 1
            else {}
        )
        if older == 0:
            winds["jet250"] = (0.0, 30.0)
        files, codes = {}, {}
        for lid, x in fields.items():
            codes[lid] = _codes(lid, x)
            files[f"{lid}.png"] = scalar_png(codes[lid])
        for lid, (u, v) in winds.items():
            ones = np.ones((360, 720))
            codes[lid] = _codes(lid, np.hypot(u, v) * ones)
            files[f"{lid}.png"] = scalar_png(codes[lid])
            files[f"{lid}_uv.png"] = vector_png(_uv_codes(lid, u * ones), _uv_codes(lid, v * ones))
        for eid, x, masked in (
            ("t_skin", np.where(lat > 0, 288.0, 300.0), np.zeros_like(lat, bool)),
            ("j_opt", np.full_like(lat, 100.0), lat < 0),
        ):
            e = EXTRAS[eid]
            codes[eid] = quantise(x, masked, *e.encode, step=e.resolution)[0]
        anomalies, _ = encode_anomalies(
            {k: _Field(x) for k, x in fields.items() if k in CLIM}, int(day[5:7]), climatology
        )
        files.update(anomalies)
        points = {k: v for k, v in point_tiles(codes).items() if k in FIXTURE_TILES}
        publish_date(data, day, files, built_at="2026-10-18T00:00:00Z", points=points)
    build_series(data)
    for p in (data / "series").rglob("*.bin"):
        if p.name not in FIXTURE_TILES:
            p.unlink()


if __name__ == "__main__":
    unit_fixtures()
    e2e_fixtures()
    for p in sorted(
        [*(ROOT / "web/tests/fixtures").rglob("*.*"), *(ROOT / "web/e2e/fixtures").rglob("*.*")]
    ):
        print(p.relative_to(ROOT), p.stat().st_size, "bytes")
