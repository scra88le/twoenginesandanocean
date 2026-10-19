import math

import pytest

from pipeline.layers import ANOMALY, LAYERS, NATURAL, VECTOR

SPEC_IDS = [
    "asr_toa", "asr_sfc", "net_toa", "olr", "t_emit", "carnot", "g_max", "j_conv", "j_ratio",
    "lh", "sh", "evap_frac", "wind10", "wind100", "jet250", "ke_col", "diss_bl", "tcwv",
    "precip", "p_lift", "div_e", "flux_e", "human_q", "human_ratio",
]  # fmt: skip


def test_ids_match_the_spec_exactly_and_in_order():
    assert list(LAYERS) == SPEC_IDS


def test_natural_layers_have_anomalies_and_human_layers_do_not():
    assert NATURAL == tuple(i for i in SPEC_IDS if not i.startswith("human_"))
    for lid, spec in LAYERS.items():
        assert spec.anomaly == (lid in NATURAL)


def test_vector_layers():
    assert set(VECTOR) == {"wind10", "wind100", "jet250", "flux_e"}
    for lid in VECTOR:
        assert LAYERS[lid].uv_encode is not None
    for lid in set(LAYERS) - set(VECTOR):
        assert LAYERS[lid].uv_encode is None


def test_groups_are_1_to_9():
    assert sorted({s.group for s in LAYERS.values()}) == list(range(1, 10))


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
