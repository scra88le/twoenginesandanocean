import numpy as np
import pytest
import xarray as xr

from pipeline import derived as d

NLAT, NLON = 360, 720
LAT = 89.75 - 0.5 * np.arange(NLAT)
LON = -179.75 + 0.5 * np.arange(NLON)
PHI = np.deg2rad(LAT)[:, None] * np.ones(NLON)[None, :]
LAM = np.ones(NLAT)[:, None] * np.deg2rad(LON)[None, :]
A = d.EARTH_RADIUS


# ---- spec fixtures ---------------------------------------------------------------------


def test_fixture_emission_temperature():
    assert d.emission_temperature(240.0) == pytest.approx(255.1, abs=0.05)


def test_fixture_carnot():
    eta, clamped = d.carnot_efficiency(300.0, 255.0)
    assert eta == pytest.approx(0.15)
    assert not clamped


def test_fixture_max_power():
    j_opt, g_max = d.max_power(200.0, 300.0, 255.0)
    assert j_opt == pytest.approx(100.0)
    assert g_max == pytest.approx(8.86, abs=0.005)


# ---- point formulas --------------------------------------------------------------------


def test_carnot_is_clamped_at_zero_and_flagged():
    eta, clamped = d.carnot_efficiency(np.array([250.0, 300.0]), np.array([260.0, 255.0]))
    np.testing.assert_allclose(eta, [0.0, 0.15])
    np.testing.assert_array_equal(clamped, [True, False])


def test_max_power_clips_emission_temperature_in_k_r():
    _, g_cold = d.max_power(200.0, 300.0, 150.0)  # T_e clipped up to 230 K
    _, g_230 = d.max_power(200.0, 300.0, 230.0)
    _, g_hot = d.max_power(200.0, 300.0, 400.0)  # clipped down to 290 K
    _, g_290 = d.max_power(200.0, 300.0, 290.0)
    assert g_cold == pytest.approx(g_230) and g_hot == pytest.approx(g_290)


def test_max_power_is_the_maximum_of_the_single_column_model():
    # G(J) = J (R_s - J) / (k_r T_s); J_opt and G_max must be its maximum.
    r_s, t_s, t_e = 200.0, 300.0, 255.0
    k_r = 4 * d.SIGMA * t_e**3
    j = np.linspace(0, r_s, 2001)
    g = j * (r_s - j) / (k_r * t_s)
    j_opt, g_max = d.max_power(r_s, t_s, t_e)
    assert j[np.argmax(g)] == pytest.approx(j_opt, abs=0.1)
    assert g.max() == pytest.approx(g_max, rel=1e-6)


def test_evaporative_fraction_and_mask():
    ef, masked = d.evaporative_fraction(np.array([60.0, 5.0]), np.array([20.0, 2.0]))
    assert ef[0] == pytest.approx(0.75)
    np.testing.assert_array_equal(masked, [False, True])  # LE + H < 10 W m-2


def test_lifting_power_uses_g_and_h_lift():
    p = 3.0 / 86_400  # 3 mm/day as kg m-2 s-1
    assert d.lifting_power(p) == pytest.approx(p * 9.81 * 3000.0)
    assert d.lifting_power(p, h_lift=1000.0) == pytest.approx(p * 9.81 * 1000.0)


def test_wind_speed():
    assert d.wind_speed(3.0, -4.0) == pytest.approx(5.0)


def test_human_ratio_masks_low_dissipation():
    r, masked = d.human_ratio(np.array([1.0, 1.0]), np.array([2.0, 0.005]))
    assert r[0] == pytest.approx(0.5)
    np.testing.assert_array_equal(masked, [False, True])


# ---- spherical operator and solvers ----------------------------------------------------


def test_laplacian_of_constant_is_zero():
    np.testing.assert_allclose(d.laplacian(np.full((NLAT, NLON), 5.0)), 0.0, atol=1e-20)


def test_laplacian_matches_analytic_on_the_sphere():
    # Del^2 sin(phi) = -2 sin(phi) / a^2 (a degree-1 spherical harmonic).
    lap = d.laplacian(np.sin(PHI))
    expected = -2 * np.sin(PHI) / A**2
    interior = slice(2, -2)  # pole rows carry the largest discretisation error
    np.testing.assert_allclose(lap[interior], expected[interior], rtol=1e-3, atol=1e-18)


def test_laplacian_matches_analytic_for_zonal_wave():
    # Y_2^1 ~ sin(phi) cos(phi) cos(lambda): eigenvalue -l(l+1)/a^2 = -6/a^2.
    y = np.sin(PHI) * np.cos(PHI) * np.cos(LAM)
    lap = d.laplacian(y)
    expected = -6 * y / A**2
    # second-order accurate: error within 0.1% of the field's scale everywhere off the poles
    np.testing.assert_allclose(
        lap[2:-2], expected[2:-2], rtol=0, atol=1e-3 * np.abs(expected).max()
    )


def test_laplacian_integrates_to_zero():
    rng = np.random.default_rng(0)
    lap = d.laplacian(rng.normal(size=(NLAT, NLON)))
    area = d.cell_areas()
    assert abs((lap * area).sum()) < 1e-9 * np.abs(lap * area).sum()


def test_poisson_recovers_the_potential():
    rng = np.random.default_rng(1)
    chi = rng.normal(size=(NLAT, NLON))
    chi -= d.global_mean(chi)
    got = d.solve_poisson(d.laplacian(chi))
    np.testing.assert_allclose(got, chi, atol=1e-8 * np.abs(chi).max())


def test_poisson_removes_a_nonzero_global_mean():
    rng = np.random.default_rng(2)
    chi = rng.normal(size=(NLAT, NLON))
    chi -= d.global_mean(chi)
    src = d.laplacian(chi) + 3e-12  # a constant offset can't be the divergence of anything
    np.testing.assert_allclose(d.solve_poisson(src), chi, atol=1e-8 * np.abs(chi).max())


def test_smoothing_preserves_constant_and_global_mean():
    np.testing.assert_allclose(d.smooth(np.full((NLAT, NLON), 7.0), 300e3), 7.0)
    rng = np.random.default_rng(3)
    x = rng.normal(size=(NLAT, NLON))
    assert d.global_mean(d.smooth(x, 300e3)) == pytest.approx(d.global_mean(x), abs=1e-12)


def test_smoothing_damps_grid_noise_but_not_large_scales():
    rng = np.random.default_rng(4)
    big = np.sin(PHI)  # degree-1 pattern, wavelength ~ 40 000 km
    noise = rng.normal(size=(NLAT, NLON))
    out = d.smooth(big + noise, 300e3)
    resid_big = out - big
    # degree-1 is damped by 1 / (1 + 2 L^2 / a^2), about 0.4%
    assert np.sqrt(np.mean(resid_big[5:-5] ** 2)) < 0.1 * np.sqrt(np.mean(noise**2))


def test_smoothing_with_zero_length_is_identity():
    rng = np.random.default_rng(5)
    x = rng.normal(size=(NLAT, NLON))
    np.testing.assert_allclose(d.smooth(x, 0.0), x)


def test_smoothing_is_the_implicit_diffusion_operator():
    rng = np.random.default_rng(6)
    x = rng.normal(size=(NLAT, NLON))
    length = 200e3
    s = d.smooth(x, length)
    np.testing.assert_allclose(s - length**2 * d.laplacian(s), x, atol=1e-8)


def test_divergent_flux_of_a_known_potential():
    # chi = a sin(phi): grad chi = (0, cos(phi)); its Laplacian is -2 sin(phi) / a.
    u, v = d.divergent_flux(-2 * np.sin(PHI) / A)
    np.testing.assert_allclose(v[2:-2], np.cos(PHI)[2:-2], rtol=2e-3)
    np.testing.assert_allclose(u, 0.0, atol=1e-9)


def test_meridional_transport_obeys_gauss_exactly():
    # Northward transport across each latitude edge equals minus the source north of it.
    rng = np.random.default_rng(7)
    src = rng.normal(size=(NLAT, NLON))
    src -= d.global_mean(src)
    t = d.meridional_transport(src)
    assert t.shape == (NLAT - 1,)  # interior edges between rows
    north_cap = -np.cumsum((src * d.cell_areas()).sum(axis=1))[:-1]
    np.testing.assert_allclose(t, north_cap, rtol=1e-8, atol=1e-8 * np.abs(north_cap).max())


# ---- assembling layers -----------------------------------------------------------------


def tidy(**overrides):
    base = {
        "tsr": 300.0,
        "olr": d.SIGMA * 255.0**4,
        "ssr": 200.0,
        "skt": 300.0,
        "le": 60.0,
        "h": 20.0,
        "bld": 2.0,
        "tcwv": 25.0,
        "tp": 3.0 / 86_400,
        "u10": 3.0,
        "v10": 4.0,
        "u100": 6.0,
        "v100": 8.0,
        "u250": 30.0,
        "v250": 40.0,
        "p59.162": 2.0e6,
        "p86.162": 0.0,
        "lsm": 1.0,
    }
    base.update(overrides)
    lsm = base.pop("lsm")
    fields = {
        k: (("latitude", "longitude"), np.full((NLAT, NLON), float(v))) for k, v in base.items()
    }
    lsm_field = np.full((NLAT, NLON), float(lsm))
    lsm_field[NLAT // 2 :] = 0.0  # southern hemisphere is ocean
    fields["lsm"] = (("latitude", "longitude"), lsm_field)
    return xr.Dataset(
        fields, coords={"latitude": LAT, "longitude": LON}, attrs={"date": "2026-10-01"}
    )


NATURAL = {
    "asr_toa",
    "asr_sfc",
    "net_toa",
    "olr",
    "t_emit",
    "carnot",
    "g_max",
    "j_conv",
    "j_ratio",
    "lh",
    "sh",
    "evap_frac",
    "wind10",
    "wind100",
    "jet250",
    "ke_col",
    "diss_bl",
    "tcwv",
    "precip",
    "p_lift",
    "div_e",
    "flux_e",
}


def test_compute_layers_returns_every_natural_layer():
    assert set(d.compute_layers(tidy())) == NATURAL


def test_layers_are_in_catalogue_units():
    lay = d.compute_layers(tidy())
    north = (0, 0)
    assert lay["carnot"].values[north] == pytest.approx(15.0)  # percent
    assert lay["t_emit"].values[north] == pytest.approx(255.0)
    assert lay["net_toa"].values[north] == pytest.approx(300.0 - d.SIGMA * 255.0**4)
    assert lay["ke_col"].values[north] == pytest.approx(2.0)  # MJ m-2
    assert lay["precip"].values[north] == pytest.approx(3.0)  # mm/day
    assert lay["j_conv"].values[north] == pytest.approx(80.0)
    assert lay["wind100"].values[north] == pytest.approx(10.0)
    assert lay["evap_frac"].values[north] == pytest.approx(0.75)
    assert lay["g_max"].values[north] == pytest.approx(8.86, abs=0.005)
    assert lay["j_ratio"].values[north] == pytest.approx(0.8)


def test_land_only_layers_are_masked_over_ocean():
    lay = d.compute_layers(tidy())
    for name in ("g_max", "j_ratio"):
        assert not lay[name].masked.values[0].any()  # northern rows are land
        assert lay[name].masked.values[-1].all()  # southern rows are ocean
    assert not lay["carnot"].masked.values.any()


def test_j_ratio_is_masked_where_there_is_almost_no_sunlight():
    lay = d.compute_layers(tidy(ssr=5.0))
    assert lay["j_ratio"].masked.values.all()


def test_vector_layers_keep_components():
    lay = d.compute_layers(tidy())
    for name, (u, v) in {"wind10": (3, 4), "wind100": (6, 8), "jet250": (30, 40)}.items():
        assert lay[name].u.values[0, 0] == pytest.approx(u)
        assert lay[name].v.values[0, 0] == pytest.approx(v)
    assert lay["flux_e"].u is not None and lay["flux_e"].v is not None


def test_flux_e_is_zero_for_a_uniform_divergence():
    # A uniform divergence is all global mean, which is removed: no transport.
    lay = d.compute_layers(tidy(**{"p86.162": 12.0}))
    np.testing.assert_allclose(lay["flux_e"].values, 0.0, atol=1e-6)
    np.testing.assert_allclose(lay["div_e"].values, 12.0)


def test_layers_are_dataarrays_on_the_grid():
    lay = d.compute_layers(tidy())
    for f in lay.values():
        assert isinstance(f.values, xr.DataArray)
        assert f.values.shape == (NLAT, NLON)
        assert f.masked.dtype == bool
