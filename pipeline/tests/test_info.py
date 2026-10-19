import pytest

from pipeline import derived
from pipeline.info import INFO
from pipeline.layers import LAYERS

FIELDS = ("summary", "source", "formula", "sign", "meaning", "caveats")


def test_every_layer_has_info_and_nothing_else_does():
    assert set(INFO) == set(LAYERS)


@pytest.mark.parametrize("lid", list(LAYERS))
def test_info_is_complete(lid):
    info = INFO[lid]
    for f in FIELDS:
        assert getattr(info, f).strip(), f"{lid}.{f} is empty"


@pytest.mark.parametrize("lid", list(LAYERS))
def test_summary_is_one_short_line(lid):
    s = INFO[lid].summary
    assert "\n" not in s and len(s) <= 100


@pytest.mark.parametrize("lid", [i for i in LAYERS if not i.startswith("human_")])
def test_natural_layers_name_era5_as_their_source(lid):
    assert "ERA5" in INFO[lid].source


def test_config_values_are_filled_in_from_derived():
    assert f"{derived.H_LIFT_M:.0f} m" in INFO["p_lift"].formula
    assert f"{derived.SMOOTH_LENGTH_M / 1e3:.0f} km" in INFO["div_e"].formula
    for info in INFO.values():
        for f in FIELDS:
            assert "{" not in getattr(info, f), "unfilled placeholder"


def test_masked_layers_explain_their_mask():
    for lid in ("g_max", "j_ratio", "evap_frac", "human_ratio"):
        assert INFO[lid].mask
    for lid in ("olr", "precip", "carnot"):
        assert INFO[lid].mask is None


def test_p_lift_is_labelled_indicative():
    assert "indicative" in INFO["p_lift"].summary.lower()
    assert "indicative" in LAYERS["p_lift"].title.lower()


def test_flipped_fluxes_state_the_sign_convention():
    for lid in ("olr", "lh", "sh", "j_conv"):
        assert "upward" in INFO[lid].sign.lower()


def test_every_layer_says_how_its_anomaly_is_made_or_why_there_is_none():
    from pipeline.layers import ANOMALY, LAYERS

    for lid in LAYERS:
        text = INFO[lid].anomaly
        assert text
        if lid in ANOMALY:
            assert "1991–2020" in text and ("Exact" in text or "approximation" in text)
        else:
            assert text.startswith("No anomaly")
    assert "approximation" in INFO["carnot"].anomaly and "Exact" in INFO["olr"].anomaly
