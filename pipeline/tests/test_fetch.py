from datetime import date

import pytest

from pipeline.fetch import (
    ACCUMULATED,
    PRESSURE_DAILY,
    SINGLE_DAILY,
    VARIABLES,
    build_requests,
)

D = date(2026, 10, 1)


def by_name():
    return {spec.name: spec for spec in build_requests(D)}


def test_three_requests_per_date():
    assert set(by_name()) == {"single_mean", "single_sum", "pressure_mean"}


def test_common_parameters():
    for spec in build_requests(D):
        r = spec.request
        assert r["product_type"] == "reanalysis"
        assert r["time_zone"] == "utc+00:00"
        assert r["frequency"] == "1_hourly"
        assert (r["year"], r["month"], r["day"]) == ("2026", "10", "01")


def test_date_parts_are_zero_padded_strings():
    r = by_name()["single_mean"].request
    assert r["month"] == "10" and r["day"] == "01"
    r = {s.name: s for s in build_requests(date(2026, 3, 9))}["single_mean"].request
    assert (r["month"], r["day"]) == ("03", "09")


def test_accumulated_variables_use_daily_sum_only():
    specs = by_name()
    summed = set(specs["single_sum"].request["variable"])
    meaned = set(specs["single_mean"].request["variable"])
    assert specs["single_sum"].request["daily_statistic"] == "daily_sum"
    assert specs["single_mean"].request["daily_statistic"] == "daily_mean"
    assert summed == {VARIABLES[s].cds_name for s in ACCUMULATED}
    assert not summed & meaned


def test_every_single_level_variable_is_requested_exactly_once():
    specs = by_name()
    requested = specs["single_sum"].request["variable"] + specs["single_mean"].request["variable"]
    expected = [v.cds_name for v in VARIABLES.values() if v.collection == SINGLE_DAILY]
    assert sorted(requested) == sorted(expected)


def test_pressure_request_is_250_hpa_winds_daily_mean():
    spec = by_name()["pressure_mean"]
    assert spec.collection_id == PRESSURE_DAILY
    assert spec.request["pressure_level"] == ["250"]
    assert spec.request["daily_statistic"] == "daily_mean"
    assert sorted(spec.request["variable"]) == ["u_component_of_wind", "v_component_of_wind"]


def test_accumulated_set_matches_ingestion_rules():
    assert {"tsr", "ttr", "ssr", "slhf", "sshf", "bld", "tp"} == set(ACCUMULATED)


def test_filenames_are_unique_and_dated():
    names = [s.filename for s in build_requests(D)]
    assert len(set(names)) == len(names)
    assert all("2026-10-01" in n for n in names)


@pytest.mark.parametrize("bad", ["2026-10-01", 20261001, None])
def test_rejects_non_date(bad):
    with pytest.raises(TypeError):
        build_requests(bad)


def test_credentials_from_env_take_precedence(tmp_path):
    from pipeline.fetch import read_credentials

    rc = tmp_path / "rc"
    rc.write_text("url: https://file.example/api\nkey: filekey\n")
    env = {"CDSAPI_URL": "https://env.example/api", "CDSAPI_KEY": "envkey"}
    assert read_credentials(env, rc) == ("https://env.example/api", "envkey")


def test_credentials_from_rc_file(tmp_path):
    from pipeline.fetch import read_credentials

    rc = tmp_path / "rc"
    rc.write_text("url: https://file.example/api\nkey: abc:def\n")
    assert read_credentials({}, rc) == ("https://file.example/api", "abc:def")


def test_missing_credentials_error_does_not_leak_paths_or_keys(tmp_path):
    from pipeline.fetch import read_credentials

    with pytest.raises(RuntimeError, match="CDSAPI_KEY"):
        read_credentials({}, tmp_path / "missing")
