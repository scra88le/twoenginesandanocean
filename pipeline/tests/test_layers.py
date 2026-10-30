import math

import pytest

from pipeline.layers import ADVANCED, ANOMALY, GROUP_BLURBS, GROUPS, LAYERS, MENU, NATURAL, VECTOR

SPEC_IDS = [
    "asr_toa", "asr_sfc", "net_toa", "olr", "t_emit", "carnot", "g_max", "j_conv", "j_ratio",
    "lh", "sh", "evap_frac", "wind10", "wind100", "jet250", "ke_col", "diss_bl", "tcwv",
    "precip", "p_lift", "div_e", "flux_e", "human_q", "human_ratio", "net_sfc",
]  # fmt: skip


def test_ids_match_the_spec_exactly_and_in_order():
    assert list(LAYERS) == SPEC_IDS


def test_natural_layers_have_anomalies_and_human_layers_do_not():
    assert NATURAL == tuple(i for i in SPEC_IDS if not i.startswith("human_"))
    assert NATURAL[-1] == "net_sfc"  # appended last, so earlier point-chunk fields keep their place
    for lid, spec in LAYERS.items():
        assert spec.anomaly == (lid in NATURAL)


def test_vector_layers():
    assert set(VECTOR) == {"wind10", "wind100", "jet250", "flux_e"}
    for lid in VECTOR:
        assert LAYERS[lid].uv_encode is not None
    for lid in set(LAYERS) - set(VECTOR):
        assert LAYERS[lid].uv_encode is None


def test_groups_follow_the_title_of_the_site():
    assert GROUPS == {
        1: "Engine one: surface to sky",
        2: "Engine two: tropics to poles",
        3: "The ocean",
        4: "Water",
        5: "Humans",
    }
    assert set(GROUP_BLURBS) == set(GROUPS) and all(GROUP_BLURBS.values())
    assert sorted({s.group for s in LAYERS.values()}) == [1, 2, 3, 4, 5]
    assert LAYERS["net_sfc"].group == 3


def test_menu_lists_every_layer_once_in_the_proposed_order():
    assert sorted(MENU) == sorted(LAYERS)  # every layer once, none invented
    by_group = {g: [i for i in MENU if LAYERS[i].group == g] for g in GROUPS}
    assert by_group[1] == [
        "asr_sfc", "carnot", "g_max", "j_ratio", "evap_frac", "j_conv", "lh", "sh",
    ]  # fmt: skip
    assert by_group[2] == [
        "net_toa", "div_e", "flux_e", "ke_col", "jet250", "asr_toa", "olr", "t_emit", "diss_bl",
        "wind10", "wind100",
    ]  # fmt: skip
    assert by_group[3] == ["net_sfc"]
    assert by_group[4] == ["precip", "tcwv", "p_lift"]
    assert by_group[5] == ["human_q", "human_ratio"]
    assert [LAYERS[i].menu_order for i in MENU] == list(range(len(MENU)))


def test_advanced_layers_are_the_technical_ones_and_come_after_the_plain_ones():
    assert set(ADVANCED) == {
        "j_conv", "lh", "sh", "asr_toa", "olr", "t_emit", "diss_bl", "wind10", "wind100", "p_lift",
    }  # fmt: skip
    assert {i for i, s in LAYERS.items() if s.advanced} == set(ADVANCED)
    for g in GROUPS:
        flags = [LAYERS[i].advanced for i in MENU if LAYERS[i].group == g]
        assert flags == sorted(flags), f"group {g}: an advanced layer comes before a plain one"
    # the layers the story and the readout rely on are not hidden away
    plain = ("net_toa", "asr_sfc", "carnot", "j_ratio", "evap_frac", "div_e", "ke_col", "net_sfc")
    for lid in (*plain, "precip"):
        assert not LAYERS[lid].advanced


def test_net_sfc_is_a_diverging_layer_centred_on_zero():
    s = LAYERS["net_sfc"]
    assert s.colour == "balance" and s.centre == 0 and s.display == (-200, 200)
    assert s.encode[0] < -842 and s.encode[1] > 500  # the 2026-07 extremes fit
    assert s.anomaly_encode is not None  # linear in its inputs: it has an anomaly


def test_log_layers_match_the_catalogue():
    assert {i for i, s in LAYERS.items() if s.log} == {
        "diss_bl", "precip", "p_lift", "human_q", "human_ratio"
    }  # fmt: skip
    for s in LAYERS.values():
        if s.log:
            assert s.encode[0] > 0 and s.display[0] > 0


@pytest.mark.parametrize("lid", SPEC_IDS)
def test_encode_range_contains_display_range(lid):
    s = LAYERS[lid]
    if s.display is None:  # "auto"
        return
    assert s.encode[0] <= s.display[0] and s.display[1] <= s.encode[1]


def _span(lo, hi, log):
    return math.log10(hi) - math.log10(lo) if log else hi - lo


@pytest.mark.parametrize("lid", SPEC_IDS)
def test_resolution_is_fine_relative_to_the_display_range(lid):
    s = LAYERS[lid]
    lo, hi = s.display if s.display is not None else s.encode
    assert s.resolution <= _span(lo, hi, s.log) / 1000


@pytest.mark.parametrize("lid", SPEC_IDS)
def test_encode_ranges_fit_in_uint16_at_their_resolution(lid):
    s = LAYERS[lid]
    assert _span(*s.encode, s.log) / s.resolution <= 65_533
    if s.uv_encode is not None:
        assert _span(*s.uv_encode, False) / s.uv_resolution <= 65_533
    if s.anomaly_encode is not None:
        assert _span(*s.anomaly_encode, False) / s.anomaly_resolution <= 65_533


def test_spec_display_ranges_are_kept():
    assert LAYERS["carnot"].display == (0, 30)
    assert LAYERS["human_ratio"].display == (1e-4, 10)
    assert LAYERS["div_e"].display is None and LAYERS["flux_e"].display is None


def test_spec_encode_overrides():
    assert LAYERS["carnot"].encode == (0, 45)
    assert LAYERS["div_e"].encode == (-2000, 2000)
    assert LAYERS["flux_e"].uv_encode == (-1.5e9, 1.5e9)


def test_anomaly_ranges_are_symmetric_and_linear():
    for lid in ANOMALY:
        lo, hi = LAYERS[lid].anomaly_encode
        assert lo == -hi and hi > 0
        d_lo, d_hi = LAYERS[lid].anomaly_display
        assert d_lo == -d_hi and 0 < d_hi <= hi  # shown within what is stored


def test_natural_layers_have_anomalies_except_the_vector_ones():
    assert set(ANOMALY) == set(NATURAL) - set(VECTOR)
    for lid in VECTOR:
        assert LAYERS[lid].anomaly_encode is None and LAYERS[lid].anomaly_display is None
    assert LAYERS["precip"].anomaly_colour == "BrBG" and LAYERS["olr"].anomaly_colour == "balance"


CONCEPT = ("net_toa", "carnot", "g_max", "div_e", "net_sfc")
WIND = ("wind10", "wind100", "jet250")
BOTH = (
    "asr_toa", "asr_sfc", "olr", "t_emit", "j_conv", "lh", "sh", "evap_frac", "tcwv", "precip",
    "p_lift", "ke_col", "diss_bl",
)  # fmt: skip


def test_modes_follow_the_v2_table():
    for lid in CONCEPT:
        assert LAYERS[lid].modes == ("climate", "today", "anom")
        assert LAYERS[lid].default_mode == "climate"
    assert LAYERS["j_ratio"].modes == ("climate",) and LAYERS["j_ratio"].default_mode == "climate"
    for lid in BOTH:
        assert LAYERS[lid].modes == ("climate", "today", "anom")
        assert LAYERS[lid].default_mode == "today"
    for lid in WIND:
        assert LAYERS[lid].modes == ("today",) and LAYERS[lid].default_mode == "today"
    for lid in ("human_q", "human_ratio"):
        assert LAYERS[lid].modes == () and LAYERS[lid].default_mode is None


def test_flux_e_has_no_climate_raster_yet():
    # Its climate frames are arrows only (clim/{frame}/flux_e_uv.png); see DECISIONS.md.
    assert LAYERS["flux_e"].modes == ("today",)


def test_modes_agree_with_the_anomaly_and_default_is_supported():
    for lid, s in LAYERS.items():
        assert ("anom" in s.modes) == (s.anomaly_encode is not None and lid != "j_ratio")
        assert s.default_mode is None or s.default_mode in s.modes
