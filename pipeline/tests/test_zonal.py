import numpy as np
import pytest

from pipeline import derived as d
from pipeline import zonal

NLAT, NLON = d.NLAT, d.NLON
LAT = 89.75 - 0.5 * np.arange(NLAT)
SIN = np.sin(np.deg2rad(LAT))[:, None] * np.ones(NLON)[None, :]


def test_two_box_kleidon_fixture():
    # Kleidon (2023): R_s,t = 306 and R_s,p = 177 W m-2
    box = zonal.two_box(306.0, 177.0)
    assert box["j_opt"] == pytest.approx(32.25)
    assert box["t_tropics"] == pytest.approx(305.3, abs=0.1)
    assert box["t_poles"] == pytest.approx(275.6, abs=0.1)
    assert box["delta_t"] == pytest.approx(29.7, abs=0.1)
    assert box["g_max"] == pytest.approx(1.57, abs=0.01)


def test_boxes_are_equal_area():
    row = d._AREA_ROW
    tropics = np.abs(LAT) < zonal.SPLIT_LAT
    assert row[tropics].sum() == pytest.approx(row[~tropics].sum(), rel=1e-9)


def test_transport_is_zero_at_both_poles_and_has_361_edges():
    net = 100 * SIN**2 - 30.0  # arbitrary, with a non-zero mean
    t = zonal.transport_pw(net)
    assert t.shape == (NLAT + 1,)
    assert t[0] == 0.0 and t[-1] == 0.0


def test_transport_matches_the_integral_of_the_surplus():
    # Gauss: transport across a latitude = minus the area integral of the surplus north of it
    net = 150 * np.cos(np.deg2rad(LAT))[:, None] * np.ones(NLON)[None, :] - 20.0
    t = zonal.transport_pw(net)
    anomaly = net - d.global_mean(net)
    row_int = (anomaly * d.cell_areas()).sum(axis=1)  # W per row, north to south
    i = 120  # edge between rows 119 and 120
    assert t[i] == pytest.approx(-row_int[:i].sum() / 1e15, rel=1e-3)
    # surplus in the tropics carries heat poleward
    assert t[60] > 0 > t[300]


def test_transport_atm_equals_flux_e_zonal_integral():
    div = 80 * np.cos(2 * np.deg2rad(LAT))[:, None] * np.ones(NLON)[None, :]
    u, v = d.divergent_flux(div)
    edge_v = 0.5 * (v[:-1] + v[1:]).mean(axis=1)
    length = d.EARTH_RADIUS * d._COS_EDGE[1:-1] * np.deg2rad(0.5) * NLON
    expected = edge_v * length / 1e15
    t = zonal.transport_pw(div)
    assert t[1:-1] == pytest.approx(expected, abs=0.02 * np.abs(expected).max())


def test_zonal_means_and_global_block():
    asr = 240 + 100 * SIN**2 * 0 + 50 * np.cos(np.deg2rad(LAT))[:, None] * np.ones(NLON)[None, :]
    olr = np.full_like(asr, 240.0)
    summary = zonal.zonal_summary(
        {"asr_toa": asr, "olr": olr, "skt": np.full_like(asr, 288.0),
         "div_e": asr - olr, "j_conv": np.full_like(asr, 100.0),
         "carnot": np.full_like(asr, 12.0), "diss_bl": np.full_like(asr, 2.0)},
        year=True,
    )  # fmt: skip
    assert len(summary["lat"]) == NLAT
    assert summary["net_toa"] == pytest.approx(list(asr[:, 0] - 240.0), abs=1e-3)
    g = summary["global"]
    assert g["asr_toa"] == pytest.approx(d.global_mean(asr))
    assert g["imbalance"] == pytest.approx(g["asr_toa"] - g["olr"], abs=1e-3)
    assert g["diss_bl_pct"] == pytest.approx(100 * 2.0 / g["asr_toa"], abs=1e-3)
    assert "two_box" in summary and "transport_ocean" in summary


def test_non_year_frames_omit_two_box_and_ocean():
    f = np.full((NLAT, NLON), 100.0)
    s = zonal.zonal_summary(
        {"asr_toa": f, "olr": f, "skt": f, "div_e": f * 0, "j_conv": f, "carnot": f,
         "diss_bl": f}, year=False,
    )  # fmt: skip
    assert "two_box" not in s and "transport_ocean" not in s


def test_year_global_block_has_overview_slots():
    asr = 240 + 50 * np.cos(np.deg2rad(LAT))[:, None] * np.ones(NLON)[None, :]
    olr = np.full_like(asr, 240.0)
    f = lambda v: np.full_like(asr, v)  # noqa: E731
    base = {"asr_toa": asr, "olr": olr, "skt": f(288.0), "div_e": asr - olr, "j_conv": f(100.0),
            "carnot": f(12.0), "diss_bl": f(2.0)}  # fmt: skip
    s = zonal.zonal_summary(
        {**base, "asr_sfc": f(160.0), "lw_up": f(60.0), "lh": f(80.0), "sh": f(20.0),
         "precip": f(2.9)}, year=True,
    )  # fmt: skip
    g = s["global"]
    assert g["asr_sfc"] == 160.0 and g["lw_up"] == 60.0 and g["precip"] == 2.9
    assert g["t_skin"] == pytest.approx(288.0)
    assert g["asr_atm"] == pytest.approx(g["asr_toa"] - 160.0, abs=1e-3)
    assert g["t_r"] == pytest.approx((g["asr_toa"] / d.SIGMA) ** 0.25, abs=1e-2)
    assert g["pw_atm"] == pytest.approx(np.abs(s["transport_atm"]).max(), abs=1e-3)
    assert g["pw_ocean"] == pytest.approx(np.abs(s["transport_ocean"]).max(), abs=1e-3)
    # optional layers that were not supplied are left out, never zero
    bare = zonal.zonal_summary(base, year=True)["global"]
    assert "lw_up" not in bare and "asr_atm" not in bare and "t_skin" in bare
    # other frames keep the old block
    assert "t_r" not in zonal.zonal_summary(base, year=False)["global"]
