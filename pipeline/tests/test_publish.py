import json
from datetime import date, timedelta

import numpy as np
import pytest
from _helpers import synthetic_tidy

from pipeline import derived, publish
from pipeline.encode import decode, png_to_ints
from pipeline.layers import LAYERS, NATURAL, VECTOR

D = "2026-10-01"


@pytest.fixture(scope="module")
def layers():
    return derived.compute_layers(synthetic_tidy())


@pytest.fixture(scope="module")
def encoded(layers):
    return publish.encode_date(layers)


def test_every_natural_layer_gets_a_png_and_vectors_get_uv(encoded):
    files, _, _ = encoded
    expected = {f"{i}.png" for i in NATURAL} | {f"{i}_uv.png" for i in VECTOR}
    assert set(files) == expected


def test_encoded_values_decode_back(encoded, layers):
    files, _, _ = encoded
    spec = LAYERS["carnot"]
    got = decode(png_to_ints(files["carnot.png"]), *spec.encode, step=spec.resolution)
    assert got[0, 0] == pytest.approx(15.0, abs=1e-3)
    spec = LAYERS["g_max"]
    got = decode(png_to_ints(files["g_max.png"]), *spec.encode, step=spec.resolution)
    assert np.isnan(got[-1]).all()  # ocean is masked


def test_uv_png_decodes_to_components(encoded):
    files, _, _ = encoded
    u, v = png_to_ints(files["wind100_uv.png"])
    lo, hi = LAYERS["wind100"].uv_encode
    step = LAYERS["wind100"].uv_resolution
    assert decode(u, lo, hi, step=step)[0, 0] == pytest.approx(6.0, abs=step / 2)
    assert decode(v, lo, hi, step=step)[0, 0] == pytest.approx(8.0, abs=step / 2)


def test_stats_count_masked_nodata_and_clipped(encoded):
    _, stats, _ = encoded
    assert stats["g_max"]["masked_pct"] == pytest.approx(50.0)
    assert stats["carnot"]["nodata_pct"] == 0.0
    assert stats["carnot"]["clipped"] == 0


def test_publish_writes_fields_and_manifest(tmp_path, encoded):
    files, _, _ = encoded
    publish.publish_date(tmp_path, D, files, built_at="2026-10-18T00:00:00Z")
    assert (tmp_path / "fields" / D / "carnot.png").is_file()
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["dates"] == [D]
    assert m["built_at"] == "2026-10-18T00:00:00Z"
    assert m["codes"] == {"nodata": 0, "masked": 1, "first_valid": 2}
    lay = m["layers"]["precip"]
    assert lay["log"] is True and lay["units"] == "mm day-1"
    assert lay["encode"]["offset"] == pytest.approx(-3.0)
    assert lay["encode"]["scale"] == pytest.approx(0.002)
    assert m["layers"]["wind10"]["uv_encode"]["offset"] == pytest.approx(-60.0)
    assert m["layers"]["div_e"]["display"] == "auto"
    assert list(m["layers"]) == list(LAYERS)
    assert "Copernicus" in m["credits"]


def test_republishing_a_date_replaces_it_cleanly(tmp_path, encoded):
    files, _, _ = encoded
    publish.publish_date(tmp_path, D, {"old.png": b"x", **files})
    publish.publish_date(tmp_path, D, files)
    assert not (tmp_path / "fields" / D / "old.png").exists()
    assert json.loads((tmp_path / "manifest.json").read_text())["dates"] == [D]
    assert [p.name for p in (tmp_path / "fields").iterdir()] == [D]  # no temp dirs left


def test_failed_write_leaves_the_published_site_untouched(tmp_path, encoded, monkeypatch):
    files, _, _ = encoded
    publish.publish_date(tmp_path, D, files)
    before = (tmp_path / "fields" / D / "carnot.png").read_bytes()
    manifest_before = (tmp_path / "manifest.json").read_text()

    real_write = publish._write_file
    calls = {"n": 0}

    def flaky(path, data):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        real_write(path, data)

    monkeypatch.setattr(publish, "_write_file", flaky)
    with pytest.raises(OSError):
        publish.publish_date(tmp_path, D, {k: b"broken" for k in files})
    assert (tmp_path / "fields" / D / "carnot.png").read_bytes() == before
    assert (tmp_path / "manifest.json").read_text() == manifest_before
    assert [p.name for p in (tmp_path / "fields").iterdir()] == [D]


def test_failed_manifest_write_keeps_the_old_manifest(tmp_path, encoded, monkeypatch):
    files, _, _ = encoded
    publish.publish_date(tmp_path, D, files)
    manifest_before = (tmp_path / "manifest.json").read_text()

    def boom(*a, **k):
        raise OSError("no space for manifest")

    monkeypatch.setattr(publish, "_write_manifest", boom)
    with pytest.raises(OSError):
        publish.publish_date(tmp_path, "2026-10-02", files)
    assert (tmp_path / "manifest.json").read_text() == manifest_before


def test_only_the_newest_90_dates_are_kept(tmp_path):
    start = date(2026, 1, 1)
    days = [(start + timedelta(days=i)).isoformat() for i in range(92)]
    for day in days:
        publish.publish_date(tmp_path, day, {"x.png": b"x"}, keep_days=90)
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["dates"] == days[2:]
    assert sorted(p.name for p in (tmp_path / "fields").iterdir()) == days[2:]


def test_dates_are_sorted_and_unique(tmp_path):
    for day in ("2026-10-03", "2026-10-01", "2026-10-02", "2026-10-01"):
        publish.publish_date(tmp_path, day, {"x.png": b"x"})
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["dates"] == ["2026-10-01", "2026-10-02", "2026-10-03"]


def test_rejects_bad_date_strings(tmp_path):
    with pytest.raises(ValueError):
        publish.publish_date(tmp_path, "../etc", {"x.png": b"x"})


def test_manifest_carries_info_hatching_and_built_layers(tmp_path, encoded):
    files, _, _ = encoded
    publish.publish_date(tmp_path, D, files)
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["layers"]["carnot"]["hatch_zero"] is True
    assert m["layers"]["olr"]["hatch_zero"] is False
    assert m["layers"]["p_lift"]["info"]["formula"]
    assert m["layers"]["g_max"]["info"]["mask"]
    assert m["built_layers"] == sorted(NATURAL)


def test_built_layers_accumulate_across_publishes(tmp_path):
    publish.publish_date(
        tmp_path, "2026-10-01", {"olr.png": b"x", "wind10.png": b"x", "wind10_uv.png": b"x"}
    )
    publish.publish_date(tmp_path, "2026-10-02", {"precip.png": b"x"})
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["built_layers"] == ["olr", "precip", "wind10"]
