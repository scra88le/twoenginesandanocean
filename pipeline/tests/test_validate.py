import csv

import numpy as np
import pytest
from _helpers import synthetic_tidy

from pipeline import derived
from pipeline.publish import encode_date
from pipeline.validate import check, global_means, write_log

GOOD = dict(tsr=240.0)  # olr is sigma * 255^4 (239.8 W m-2) and tp 3 mm/day in the synthetic data


@pytest.fixture(scope="module")
def good():
    tidy = synthetic_tidy(**GOOD)
    layers = derived.compute_layers(tidy)
    return tidy, layers, encode_date(layers)[1]


def test_global_means(good):
    tidy, _, _ = good
    m = global_means(tidy)
    assert m["tsr"] == pytest.approx(240.0)
    assert m["olr"] == pytest.approx(derived.SIGMA * 255.0**4)
    assert m["tp_mm_day"] == pytest.approx(3.0)


def test_a_good_day_passes(good):
    assert check(*good) == []


@pytest.mark.parametrize(
    "override, phrase",
    [(dict(tsr=300.0), "tsr"), (dict(tsr=240.0, tp=5 / 86_400), "tp"),
     (dict(tsr=240.0, olr=200.0), "olr")],
)  # fmt: skip
def test_global_means_outside_their_ranges_fail(override, phrase):
    tidy = synthetic_tidy(**override)
    layers = derived.compute_layers(tidy)
    problems = check(tidy, layers, encode_date(layers)[1])
    assert any(phrase in p for p in problems)


def test_too_much_missing_data_fails(good):
    tidy, layers, stats = good
    stats = {**stats, "lh": {**stats["lh"], "nodata_pct": 1.5}}
    assert any("lh" in p and "no data" in p for p in check(tidy, layers, stats))


def test_carnot_above_40_percent_fails():
    tidy = synthetic_tidy(tsr=240.0, skt=500.0)  # absurd skin temperature -> carnot ~49%
    layers = derived.compute_layers(tidy)
    assert any("carnot" in p for p in check(tidy, layers, encode_date(layers)[1]))


def test_log_has_one_row_per_date_sorted_and_replaced(tmp_path):
    m = {"tsr": 240.0, "olr": 241.0, "tp_mm_day": 3.0}
    write_log(tmp_path, "2026-10-02", m, [])
    write_log(tmp_path, "2026-10-01", m, ["tsr 300.0 outside 220-260"])
    write_log(tmp_path, "2026-10-01", m, [])
    rows = list(csv.DictReader((tmp_path / "logs" / "global_means.csv").open()))
    assert [r["date"] for r in rows] == ["2026-10-01", "2026-10-02"]
    assert rows[0]["status"] == "ok" and rows[0]["problems"] == ""
    assert float(rows[1]["olr"]) == 241.0


def test_log_records_failures(tmp_path):
    write_log(tmp_path, "2026-10-01", {"tsr": 1.0, "olr": 2.0, "tp_mm_day": np.nan}, ["a", "b"])
    row = next(csv.DictReader((tmp_path / "logs" / "global_means.csv").open()))
    assert row["status"] == "failed" and row["problems"] == "a; b"
