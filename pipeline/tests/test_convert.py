import numpy as np
import pytest
import xarray as xr

from pipeline.convert import (
    SECONDS_PER_DAY,
    accumulated_to_flux,
    area_weighted_mean,
    convert_fields,
    precip_mm_per_day,
    precip_to_kg_m2_s,
    regrid_half_degree,
    tidy_dataset,
    to_lon_180,
)

LAT = np.linspace(90, -90, 721)
LON = np.arange(0, 360, 0.25)


def field(fill=None, fn=None):
    """A (721, 1440) ERA5-shaped DataArray."""
    lat2, lon2 = np.meshgrid(LAT, LON, indexing="ij")
    data = np.full(lat2.shape, fill, dtype="float64") if fn is None else fn(lat2, lon2)
    coords = {"latitude": LAT, "longitude": LON}
    return xr.DataArray(data, coords=coords, dims=("latitude", "longitude"))


# ---- units -----------------------------------------------------------------------------


def test_accumulated_energy_to_flux():
    assert accumulated_to_flux(86_400.0 * 240.0) == pytest.approx(240.0)
    assert SECONDS_PER_DAY == 86_400


def test_precip_m_per_day_to_kg_m2_s():
    # 3 mm/day = 0.003 m/day -> 3 kg m-2 day-1 -> 3/86400 kg m-2 s-1
    assert precip_to_kg_m2_s(0.003) == pytest.approx(3 / 86_400)


def test_precip_m_per_day_to_mm_per_day():
    assert precip_mm_per_day(0.003) == pytest.approx(3.0)


# ---- sign flips ------------------------------------------------------------------------


def raw_day(**values):
    """Raw ERA5 daily fields with spatially constant values."""
    return {k: field(v) for k, v in values.items()}


def test_upward_fluxes_become_positive_and_are_renamed():
    out = convert_fields(
        raw_day(
            ttr=-240.0 * 86_400,  # ERA5: downward positive, so outgoing longwave is negative
            slhf=-80.0 * 86_400,
            sshf=-20.0 * 86_400,
        )
    )
    assert float(out["olr"][0, 0]) == pytest.approx(240.0)
    assert float(out["le"][0, 0]) == pytest.approx(80.0)
    assert float(out["h"][0, 0]) == pytest.approx(20.0)
    for raw in ("ttr", "slhf", "sshf"):
        assert raw not in out


def test_downward_fluxes_are_not_flipped():
    out = convert_fields(raw_day(tsr=300.0 * 86_400, ssr=180.0 * 86_400))
    assert float(out["tsr"][0, 0]) == pytest.approx(300.0)
    assert float(out["ssr"][0, 0]) == pytest.approx(180.0)


def test_surface_longwave_is_flipped_when_present():
    out = convert_fields(raw_day(str=-60.0 * 86_400))
    assert float(out["lw_up"][0, 0]) == pytest.approx(60.0)


def test_boundary_layer_dissipation_is_converted_but_not_flipped():
    out = convert_fields(raw_day(bld=2.5 * 86_400))
    assert float(out["bld"][0, 0]) == pytest.approx(2.5)


def test_precip_converted_to_mass_flux():
    out = convert_fields(raw_day(tp=0.003))
    assert float(out["tp"][0, 0]) == pytest.approx(3 / 86_400)
    assert out["tp"].attrs["units"] == "kg m-2 s-1"


def test_state_variables_pass_through_unchanged():
    out = convert_fields(raw_day(skt=288.0, tcwv=25.0))
    assert float(out["skt"][0, 0]) == 288.0
    assert float(out["tcwv"][0, 0]) == 25.0


def test_units_attrs_are_set_on_converted_fluxes():
    out = convert_fields(raw_day(ttr=-1.0, slhf=-1.0, tsr=1.0))
    assert out["olr"].attrs["units"] == "W m-2"
    assert out["le"].attrs["units"] == "W m-2"
    assert out["tsr"].attrs["units"] == "W m-2"


def test_already_converted_names_are_rejected():
    # Flipping twice would silently give the wrong sign, so converted names are refused.
    with pytest.raises(ValueError, match="already converted"):
        convert_fields(raw_day(olr=240.0))


# ---- longitude -------------------------------------------------------------------------


def test_longitude_wraps_to_minus_180_179_75():
    da = field(fn=lambda lat, lon: lon)  # value equals the original longitude
    out = to_lon_180(da)
    assert float(out.longitude[0]) == -180.0
    assert float(out.longitude[-1]) == 179.75
    assert out.sizes["longitude"] == 1440
    # lon 270 east is -90; lon 0 stays 0; lon 180 becomes -180
    assert float(out.sel(longitude=-90.0).isel(latitude=0)) == 270.0
    assert float(out.sel(longitude=0.0).isel(latitude=0)) == 0.0
    assert float(out.sel(longitude=-180.0).isel(latitude=0)) == 180.0


# ---- regridding ------------------------------------------------------------------------


def test_regrid_shape_and_coordinates():
    out = regrid_half_degree(to_lon_180(field(1.0)))
    assert out.shape == (360, 720)
    assert float(out.latitude[0]) == 89.75 and float(out.latitude[-1]) == -89.75
    assert float(out.longitude[0]) == -179.75 and float(out.longitude[-1]) == 179.75


def test_regrid_preserves_constant_field_including_poles():
    out = regrid_half_degree(to_lon_180(field(7.5)))
    np.testing.assert_allclose(out.values, 7.5)


def test_regrid_preserves_global_area_weighted_mean():
    rng = np.random.default_rng(0)
    src = to_lon_180(field(fn=lambda lat, lon: rng.normal(size=lat.shape)))
    out = regrid_half_degree(src)
    assert area_weighted_mean(out) == pytest.approx(area_weighted_mean(src), rel=1e-10, abs=1e-12)


def test_regrid_handles_the_date_line_wrap():
    # The first column (-180) is a point centred on the date line. Half of it belongs to the
    # first 0.5-degree column and half to the last, so both get a share and no others do.
    src = to_lon_180(field(0.0))
    src.values[300, 0] = 1.0
    out = regrid_half_degree(src)
    cols = np.unique(np.nonzero(out.values)[1])
    assert list(cols) == [0, 719]
    assert out.values[:, 0].sum() == pytest.approx(out.values[:, 719].sum())


def test_regrid_pole_row_uses_pole_points_only_inside_the_cell():
    src = to_lon_180(field(0.0))
    src.values[0, :] = 100.0  # the pole row (90N) only
    out = regrid_half_degree(src)
    # the pole row is a half-width sliver (89.875-90) covering a quarter of the 89.5-90 cell
    # in latitude, weighted by area (sin), so the first output row is non-zero and the
    # second is exactly zero
    assert np.all(out.values[0] > 0)
    assert np.all(out.values[1] == 0)


def test_regrid_nan_cells_are_excluded_from_means_not_propagated():
    src = to_lon_180(field(10.0))
    src.values[100, 100] = np.nan
    out = regrid_half_degree(src)
    assert np.isfinite(out.values).all()
    np.testing.assert_allclose(out.values, 10.0)


def test_regrid_marks_mostly_missing_cells_as_nan():
    src = to_lon_180(field(10.0))
    src.values[200:203, 200:203] = np.nan  # a full 3x3 stencil of missing points
    out = regrid_half_degree(src)
    assert np.isnan(out.values).sum() >= 1


# ---- area-weighted mean ----------------------------------------------------------------


def test_area_weighted_mean_of_constant_is_constant():
    assert area_weighted_mean(field(3.0)) == pytest.approx(3.0)


def test_area_weighted_mean_weights_by_area_not_by_row():
    # 1 in the northern hemisphere, 0 in the southern, 0.5 on the equator row that straddles
    # both: exactly half the sphere's area.
    da = field(fn=lambda lat, lon: (lat > 0) + 0.5 * (lat == 0))
    assert area_weighted_mean(da) == pytest.approx(0.5, abs=1e-12)
    # sin(lat) is antisymmetric, so its area-weighted mean is zero.
    sin = field(fn=lambda lat, lon: np.sin(np.deg2rad(lat)))
    assert area_weighted_mean(sin) == pytest.approx(0.0, abs=1e-12)


def test_area_weighted_mean_ignores_nan():
    da = field(2.0)
    da.values[300:310, :] = np.nan
    assert area_weighted_mean(da) == pytest.approx(2.0)


def test_area_weighted_mean_same_on_both_grids():
    rng = np.random.default_rng(1)
    src = to_lon_180(field(fn=lambda lat, lon: rng.normal(size=lat.shape)))
    assert area_weighted_mean(regrid_half_degree(src)) == pytest.approx(
        area_weighted_mean(src), rel=1e-10, abs=1e-12
    )


# ---- tidy dataset ----------------------------------------------------------------------


def test_tidy_dataset_converts_wraps_and_regrids():
    raw = raw_day(ttr=-240.0 * 86_400, skt=288.0, lsm=1.0, tp=0.003)
    out = tidy_dataset(raw, date="2026-10-01")
    assert set(out.data_vars) == {"olr", "skt", "lsm", "tp"}
    assert out["olr"].shape == (360, 720)
    assert float(out.longitude[0]) == -179.75 and float(out.latitude[0]) == 89.75
    np.testing.assert_allclose(out["olr"].values, 240.0)
    assert out.attrs["date"] == "2026-10-01"
    assert out["olr"].attrs["units"] == "W m-2"
