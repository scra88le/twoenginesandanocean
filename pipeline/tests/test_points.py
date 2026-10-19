import json

import numpy as np
import pytest
from _helpers import synthetic_tidy

from pipeline import derived, publish
from pipeline.encode import FIRST_VALID, MASKED, NODATA, decode, scalar_png
from pipeline.layers import EXTRAS, LAYERS
from pipeline.points import (
    NTX,
    NTY,
    POINT_FIELDS,
    TILE,
    build_series,
    point_tiles,
    read_series,
    series_tiles,
)

j, i = np.mgrid[0:360, 0:720]
RAMP = ((j * 720 + i) % 60000 + FIRST_VALID).astype(np.uint16)  # a distinct code per cell


def tile_codes(data: bytes, nfields: int) -> np.ndarray:
    return np.frombuffer(data, dtype="<u2").reshape(nfields, TILE, TILE)


def test_there_are_648_tiles_of_20_by_20_cells():
    assert (NTX, NTY, TILE) == (36, 18, 20)
    assert len(point_tiles({})) == 648


def test_point_fields_are_the_layers_then_the_readout_extras():
    assert POINT_FIELDS == (*LAYERS, "t_skin", "j_opt")


def test_a_point_tile_holds_every_field_for_its_cells_little_endian():
    tiles = point_tiles({"olr": RAMP, "j_opt": RAMP[::-1]})
    data = tiles["3_2.bin"]  # columns 60..79, rows 40..59
    assert len(data) == len(POINT_FIELDS) * TILE * TILE * 2  # 20.8 kB
    t = tile_codes(data, len(POINT_FIELDS))
    k = POINT_FIELDS.index("olr")
    assert (t[k] == RAMP[40:60, 60:80]).all()
    assert (t[POINT_FIELDS.index("j_opt")] == RAMP[::-1][40:60, 60:80]).all()
    assert (t[POINT_FIELDS.index("carnot")] == NODATA).all()  # not given: no data
    # byte order: the first value of olr in this tile, as two little-endian bytes
    first = k * TILE * TILE * 2
    assert data[first] + 256 * data[first + 1] == RAMP[40, 60]


def test_point_tiles_reject_unknown_fields():
    with pytest.raises(ValueError):
        point_tiles({"nonsense": RAMP})


def test_series_tiles_carry_their_dates_and_round_trip():
    dates = ["2026-08-31", "2026-10-01"]  # with a gap
    stack = np.stack([RAMP, RAMP[::-1]])
    tiles = series_tiles(dates, stack)
    assert len(tiles) == 648
    data = tiles["35_17.bin"]  # the south-east corner tile
    assert data[:4] == b"EHS1"
    assert len(data) == 8 + 4 * 2 + 2 * TILE * TILE * 2
    got_dates, codes = read_series(data)
    assert got_dates == dates
    assert (codes[0] == RAMP[340:, 700:]).all()
    assert (codes[1] == RAMP[::-1][340:, 700:]).all()


def test_series_tiles_check_the_shape():
    with pytest.raises(ValueError):
        series_tiles(["2026-10-01"], np.stack([RAMP, RAMP]))


@pytest.fixture(scope="module")
def tidy():
    return synthetic_tidy()


def test_extras_are_t_skin_and_land_only_j_opt(tidy):
    extras = derived.compute_extras(tidy)
    assert set(extras) == set(EXTRAS)
    assert float(extras["t_skin"].values[0, 0]) == pytest.approx(300.0)
    assert float(extras["j_opt"].values[0, 0]) == pytest.approx(100.0)  # R_s / 2
    assert extras["j_opt"].masked.values[-1].all()  # ocean in the synthetic south
    assert not extras["t_skin"].masked.values.any()


def test_encode_date_returns_point_tiles_with_layers_and_extras(tidy):
    layers = derived.compute_layers(tidy)
    _, _, points = publish.encode_date(layers, derived.compute_extras(tidy))
    t = tile_codes(points["0_0.bin"], len(POINT_FIELDS))  # far north: land
    spec = EXTRAS["j_opt"]
    assert decode(t[POINT_FIELDS.index("j_opt")], *spec.encode, step=spec.resolution)[0, 0] == (
        pytest.approx(100.0, abs=spec.resolution / 2)
    )
    s = LAYERS["carnot"]
    assert decode(t[POINT_FIELDS.index("carnot")], *s.encode, step=s.resolution)[0, 0] == (
        pytest.approx(15.0, abs=s.resolution / 2)
    )
    south = tile_codes(points["0_17.bin"], len(POINT_FIELDS))
    assert (south[POINT_FIELDS.index("g_max")] == MASKED).all()
    assert (south[POINT_FIELDS.index("human_q")] == NODATA).all()  # not built


def test_publish_swaps_in_points_and_describes_them(tmp_path, tidy):
    layers = derived.compute_layers(tidy)
    files, _, points = publish.encode_date(layers, derived.compute_extras(tidy))
    publish.publish_date(tmp_path, "2026-10-01", files, points=points)
    assert len(list((tmp_path / "points" / "2026-10-01").iterdir())) == 648
    assert [p.name for p in (tmp_path / "points").iterdir()] == ["2026-10-01"]  # no temp dirs
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["points"]["fields"] == list(POINT_FIELDS)
    assert m["points"]["tile"] == 20
    assert m["points"]["file"] == "points/{date}/{tx}_{ty}.bin"
    assert m["points"]["extras"]["j_opt"]["encode"]["scale"] == pytest.approx(0.25)
    assert m["series"]["file"] == "series/{layer}/{tx}_{ty}.bin"


def test_old_points_are_pruned_with_their_dates(tmp_path):
    tiny = {"0_0.bin": b"x"}
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        publish.publish_date(tmp_path, day, {"olr.png": b"x"}, keep_days=2, points=tiny)
    assert sorted(p.name for p in (tmp_path / "points").iterdir()) == ["2026-10-02", "2026-10-03"]


def test_build_series_reads_published_pngs_and_fills_missing_dates_with_no_data(tmp_path):
    for k, day in enumerate(("2026-09-30", "2026-10-01")):
        files = {"olr.png": scalar_png((RAMP + k).astype(np.uint16))}
        if k == 1:
            files["precip.png"] = scalar_png(RAMP)
        publish.publish_date(tmp_path, day, files)
    assert build_series(tmp_path) == 2 * 648
    dates, codes = read_series((tmp_path / "series" / "olr" / "1_0.bin").read_bytes())
    assert dates == ["2026-09-30", "2026-10-01"]
    assert (codes[0] == RAMP[0:20, 20:40]).all() and (codes[1] == RAMP[0:20, 20:40] + 1).all()
    _, precip = read_series((tmp_path / "series" / "precip" / "1_0.bin").read_bytes())
    assert (precip[0] == NODATA).all()  # no precip PNG on the first date
    assert not list((tmp_path / "series" / "olr").glob("*.tmp"))


def test_build_series_without_a_manifest_does_nothing(tmp_path):
    assert build_series(tmp_path) == 0
