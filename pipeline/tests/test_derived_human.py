"""The technosphere's free-energy cascade (Kleidon): accounting formulas in `pipeline.derived`.

Written before the implementation (CLAUDE.md: test-first for `pipeline.derived`).
"""

import numpy as np
import pytest

from pipeline import derived as d

# A country with every source, in TWh per year: primary energy for the fuels, electricity
# generated for the others (the Energy Institute's columns, as Our World in Data publishes them).
SOURCES_TWH = {
    "coal": 1000.0,
    "oil": 2000.0,
    "gas": 1500.0,
    "biofuel": 100.0,
    "nuclear": 330.0,
    "hydro": 200.0,
    "wind": 150.0,
    "solar": 50.0,
    "other_renewable": 66.0,
}
SHARES = {"power": 0.4, "industry": 0.3, "transport": 0.2, "buildings": 0.1}


def _watts(twh: dict[str, float]) -> dict[str, float]:
    return {k: d.twh_per_year_to_watts(v) for k, v in twh.items()}


# ---- units -----------------------------------------------------------------------------


def test_one_terawatt_for_a_year_is_8766_twh():
    assert d.twh_per_year_to_watts(8766.0) == pytest.approx(1e12)


def test_unit_conversion_is_linear_and_vectorised():
    x = np.array([0.0, 8766.0, 17532.0])
    np.testing.assert_allclose(d.twh_per_year_to_watts(x), [0.0, 1e12, 2e12])


# ---- primary energy, direct-equivalent -------------------------------------------------


def test_direct_equivalent_counts_heat_for_thermal_plants_and_electricity_for_the_rest():
    p = d.direct_equivalent(SOURCES_TWH)
    assert p["coal"] == 1000.0 and p["oil"] == 2000.0 and p["gas"] == 1500.0
    assert p["biofuel"] == 100.0
    # Reactor heat: 330 TWh of electricity at 33 % is 1000 TWh of heat.
    assert p["nuclear"] == pytest.approx(330.0 / d.NUCLEAR_EFFICIENCY)
    assert p["nuclear"] == pytest.approx(1000.0)
    assert p["other_renewable"] == pytest.approx(66.0 / d.THERMAL_RENEWABLE_EFFICIENCY)
    # Wind, sunlight and falling water: the electricity is the free energy taken.
    assert p["hydro"] == 200.0 and p["wind"] == 150.0 and p["solar"] == 50.0


def test_direct_equivalent_treats_missing_sources_as_zero():
    p = d.direct_equivalent({"wind": 10.0})
    assert set(p) == set(d.SOURCES)
    assert p["wind"] == 10.0
    assert sum(p.values()) == 10.0


def test_every_source_has_an_engine():
    assert set(d.SOURCE_ENGINE) == set(d.SOURCES)
    assert d.SOURCE_ENGINE["coal"] == d.SOURCE_ENGINE["oil"] == d.SOURCE_ENGINE["gas"] == "fossil"
    assert d.SOURCE_ENGINE["wind"] == "atmosphere"
    assert d.SOURCE_ENGINE["hydro"] == "water"
    assert d.SOURCE_ENGINE["solar"] == "radiation"
    assert d.SOURCE_ENGINE["biofuel"] == d.SOURCE_ENGINE["other_renewable"] == "biosphere"
    assert d.SOURCE_ENGINE["nuclear"] == "none"


def test_by_engine_sums_sources_and_conserves_the_total():
    p = d.direct_equivalent(SOURCES_TWH)
    e = d.by_engine(p)
    assert e["fossil"] == pytest.approx(4500.0)
    assert e["biosphere"] == pytest.approx(100.0 + 66.0 / d.THERMAL_RENEWABLE_EFFICIENCY)
    assert sum(e.values()) == pytest.approx(sum(p.values()))


# ---- power stations --------------------------------------------------------------------


def test_plant_split_conserves_the_fuel():
    elec, losses = d.plant_split(100.0, 0.38)
    assert elec == pytest.approx(38.0)
    assert losses == pytest.approx(62.0)
    assert elec + losses == pytest.approx(100.0)


def test_plant_split_rejects_an_impossible_efficiency():
    with pytest.raises(ValueError):
        d.plant_split(100.0, 1.2)


# ---- bunkers ---------------------------------------------------------------------------


def test_remove_pro_rata_takes_a_total_in_proportion_and_conserves():
    oil = {"A": 300.0, "B": 100.0}
    kept, taken = d.remove_pro_rata(oil, 40.0)
    assert taken == {"A": pytest.approx(30.0), "B": pytest.approx(10.0)}
    assert kept == {"A": pytest.approx(270.0), "B": pytest.approx(90.0)}


def test_remove_pro_rata_cannot_take_more_than_there_is():
    with pytest.raises(ValueError):
        d.remove_pro_rata({"A": 1.0}, 2.0)


# ---- national components ---------------------------------------------------------------


def test_national_components_conserve_primary_power():
    p = _watts(d.direct_equivalent(SOURCES_TWH))
    c = d.national_components(p, SHARES)
    assert set(c) == set(d.COMPONENTS) - {"fuel_bunkers"}
    assert sum(c.values()) == pytest.approx(sum(p.values()), rel=1e-12)
    assert all(v >= 0 for v in c.values())


def test_national_components_route_each_source():
    p = d.direct_equivalent(SOURCES_TWH)  # units don't matter: the split is linear
    c = d.national_components(p, SHARES)
    fossil = 4500.0
    to_power = fossil * SHARES["power"]
    fossil_elec = to_power * d.FOSSIL_GENERATION_EFFICIENCY
    assert c["losses_fossil"] == pytest.approx(to_power - fossil_elec)
    assert c["losses_nuclear"] == pytest.approx(1000.0 - 330.0)
    assert c["losses_renewable"] == pytest.approx(66.0 / d.THERMAL_RENEWABLE_EFFICIENCY - 66.0)
    elec = fossil_elec + 330.0 + 200.0 + 150.0 + 50.0 + 66.0
    assert c["elec_industry"] == pytest.approx(elec * d.ELEC_INDUSTRY_SHARE)
    assert c["elec_buildings"] == pytest.approx(elec * (1 - d.ELEC_INDUSTRY_SHARE))
    assert c["fuel_industry"] == pytest.approx(fossil * SHARES["industry"])
    assert c["fuel_transport"] == pytest.approx(fossil * SHARES["transport"] + 100.0)  # biofuel
    assert c["fuel_buildings"] == pytest.approx(fossil * SHARES["buildings"])


def test_national_components_need_shares_that_sum_to_one():
    with pytest.raises(ValueError):
        d.national_components(d.direct_equivalent(SOURCES_TWH), {"power": 0.5, "industry": 0.2})


def test_a_country_without_fossil_fuel_needs_no_shares():
    c = d.national_components(d.direct_equivalent({"hydro": 100.0}), None)
    assert c["elec_industry"] + c["elec_buildings"] == pytest.approx(100.0)
    assert sum(c.values()) == pytest.approx(100.0)


# ---- the cascade: primary power, useful work, waste heat --------------------------------


def test_every_component_has_a_useful_fraction_between_zero_and_one():
    assert set(d.USEFUL_FRACTION) == set(d.COMPONENTS)
    assert all(0.0 <= f <= 1.0 for f in d.USEFUL_FRACTION.values())
    for name in ("losses_fossil", "losses_nuclear", "losses_renewable"):
        assert d.USEFUL_FRACTION[name] == 0.0  # conversion losses are heat at the plant


def test_cascade_work_plus_heat_is_primary_power_in_every_cell():
    rng = np.random.default_rng(1)
    comps = {c: rng.random((4, 5)) * 10 for c in d.COMPONENTS}
    p, work, heat = d.cascade(comps)
    np.testing.assert_allclose(p, sum(comps.values()))
    np.testing.assert_allclose(work + heat, p)
    assert np.all(work >= 0) and np.all(heat >= 0)


def test_cascade_applies_each_useful_fraction():
    comps = {c: np.zeros(2) for c in d.COMPONENTS}
    comps["fuel_transport"] = np.array([10.0, 0.0])
    comps["losses_fossil"] = np.array([0.0, 5.0])
    p, work, heat = d.cascade(comps)
    np.testing.assert_allclose(p, [10.0, 5.0])
    np.testing.assert_allclose(work, [10.0 * d.USEFUL_FRACTION["fuel_transport"], 0.0])
    np.testing.assert_allclose(heat, [10.0 * (1 - d.USEFUL_FRACTION["fuel_transport"]), 5.0])


def test_cascade_rejects_an_unknown_component():
    with pytest.raises(KeyError):
        d.cascade({"mystery": np.ones(2)})


def test_world_useful_fraction_is_plausible_for_a_typical_mix():
    # A rough world mix: the useful share of primary power should be 15-30 % (exergy
    # efficiency of the world energy system, De Stercke 2014; Paoli & Cullen 2020).
    world = {"coal": 45850, "oil": 55290, "gas": 41280, "biofuel": 1370, "nuclear": 2780,
             "hydro": 4430, "wind": 2510, "solar": 2140, "other_renewable": 790}  # fmt: skip
    shares = {"power": 0.40, "industry": 0.25, "transport": 0.25, "buildings": 0.10}
    c = d.national_components(_watts(d.direct_equivalent(world)), shares)
    c["fuel_bunkers"] = 0.0
    p, work, heat = d.cascade({k: np.array(v) for k, v in c.items()})
    assert 0.15 < float(work / p) < 0.30
    assert float(p) / 1e12 == pytest.approx(18.7, abs=0.3)  # TW, 2024


# ---- milestone 25: monthly factors ------------------------------------------------------


def test_days_in_month_make_a_mean_year():
    assert len(d.DAYS_IN_MONTH) == 12
    assert sum(d.DAYS_IN_MONTH) == pytest.approx(365.25)


def test_monthly_factors_have_a_day_weighted_mean_of_one():
    rng = np.random.default_rng(3)
    x = rng.random((12, 4, 5)) * 10
    f = d.monthly_factors(x)
    w = np.asarray(d.DAYS_IN_MONTH)[:, None, None]
    np.testing.assert_allclose((f * w).sum(axis=0) / 365.25, 1.0)


def test_monthly_factors_of_a_flat_year_are_one_and_follow_the_shape():
    np.testing.assert_allclose(d.monthly_factors(np.full(12, 7.0)), 1.0)
    x = np.ones(12)
    x[0] = 2.0  # January twice the other months
    f = d.monthly_factors(x)
    assert f[0] == pytest.approx(2 * f[1])
    assert f[0] > 1 > f[1]


def test_monthly_factors_are_one_where_there_is_nothing():
    x = np.zeros((12, 2))
    x[:, 1] = np.arange(1, 13)
    f = d.monthly_factors(x)
    np.testing.assert_allclose(f[:, 0], 1.0)
    assert f[11, 1] > f[0, 1]


def test_monthly_factors_reject_a_wrong_shape():
    with pytest.raises(ValueError):
        d.monthly_factors(np.ones(11))


# ---- milestone 25: the weather factor ---------------------------------------------------


def test_degree_days_heating_below_and_cooling_above_the_bases():
    t = np.array([d.HEATING_BASE_K - 10, d.HEATING_BASE_K + 1, d.COOLING_BASE_K + 4])
    np.testing.assert_allclose(d.heating_degrees(t), [10.0, 0.0, 0.0])
    np.testing.assert_allclose(d.cooling_degrees(t), [0.0, 0.0, 4.0])


def test_expected_degrees_match_a_sample_of_normal_days():
    rng = np.random.default_rng(5)
    for mean in (270.0, d.HEATING_BASE_K, 300.0):
        days = rng.normal(mean, d.DAILY_SPREAD_K, 200_000)
        assert d.expected_heating_degrees(np.array(mean)) == pytest.approx(
            d.heating_degrees(days).mean(), abs=0.02
        )
        assert d.expected_cooling_degrees(np.array(mean)) == pytest.approx(
            d.cooling_degrees(days).mean(), abs=0.02
        )


def test_weather_factor_averages_to_one_over_a_typical_month():
    rng = np.random.default_rng(7)
    for mean in (265.0, 286.0, 290.0, 303.0):
        days = rng.normal(mean, d.DAILY_SPREAD_K, 200_000)
        w = d.weather_factor(days, np.full_like(days, mean))
        assert w.mean() == pytest.approx(1.0, abs=0.005)


def test_weather_factor_rises_in_a_cold_snap_and_a_heat_wave():
    normal = np.array([270.0, 300.0])
    w = d.weather_factor(normal + np.array([-8.0, 6.0]), normal)
    assert w[0] > 1.1 and w[1] > 1.05
    mild = d.weather_factor(np.array([d.HEATING_BASE_K + 2]), np.array([270.0]))
    assert mild[0] < 1.0


def test_weather_factor_is_one_without_temperatures():
    w = d.weather_factor(np.array([np.nan, 280.0]), np.array([280.0, np.nan]))
    np.testing.assert_allclose(w, 1.0)


# ---- milestone 25: a day's flows -------------------------------------------------------


def test_human_flows_scale_only_the_buildings_part():
    p, work, heat = d.human_flows(
        p_base=np.array([4.0]), p_bldg=np.array([2.0]),
        w_base=np.array([1.0]), w_bldg=np.array([0.5]), weather=np.array([1.5]),
    )  # fmt: skip
    assert p[0] == pytest.approx(4.0 + 3.0)
    assert work[0] == pytest.approx(1.0 + 0.75)
    assert heat[0] == pytest.approx(p[0] - work[0])


def test_human_ratio_masks_calm_cells_and_leaves_missing_ones_missing():
    r, masked = d.human_ratio(np.array([2.0, 1.0, 1.0]), np.array([4.0, 0.0, np.nan]))
    assert r[0] == pytest.approx(0.5)
    assert masked.tolist() == [False, True, False]  # below 0.01 W m-2: masked
    assert np.isnan(r[2])  # no dissipation value: no data
