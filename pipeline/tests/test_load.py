import zipfile

import numpy as np
import pytest
from _helpers import make_archive, write_member

from pipeline.load import NC_TO_KEY, load_raw_archive


@pytest.fixture
def archive(tmp_path):
    members = {
        "skin_temperature_stream-oper_daily-mean.nc": ("skt", 288.0, False),
        "vertical_integral_of_divergence_of_total_energy_flux_0_daily-mean.nc": (
            "vited",
            5.0,
            False,
        ),
        "u_component_of_wind_stream-oper_daily-mean.nc": ("u", 30.0, True),
    }
    return make_archive(tmp_path / "a.nc", members, tmp_path)


def test_variables_are_keyed_by_spec_names(archive):
    raw = load_raw_archive(archive)
    assert set(raw) == {"skt", "p86.162", "u250"}


def test_extra_dimensions_are_squeezed_and_coords_dropped(archive):
    raw = load_raw_archive(archive)
    for da in raw.values():
        assert da.dims == ("latitude", "longitude")
        assert da.shape == (721, 1440)
        assert "number" not in da.coords and "valid_time" not in da.coords
        assert "pressure_level" not in da.coords


def test_values_are_loaded_as_float64(archive):
    raw = load_raw_archive(archive)
    assert raw["skt"].dtype == np.float64
    assert float(raw["u250"][0, 0]) == 30.0


def test_netcdf_to_spec_name_mapping_matches_real_files():
    # Confirmed against the files CDS returned for 2026-10-01 (GRIB param IDs 162059 etc.).
    assert NC_TO_KEY["vike"] == "p59.162"
    assert NC_TO_KEY["vited"] == "p86.162"
    assert NC_TO_KEY["vitee"] == "p75.162"
    assert NC_TO_KEY["viten"] == "p76.162"
    assert NC_TO_KEY["u"] == "u250" and NC_TO_KEY["v"] == "v250"


def test_unsafe_member_names_are_rejected(tmp_path):
    zpath = tmp_path / "bad.nc"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("../evil.nc", b"x")
    with pytest.raises(ValueError, match="unsafe"):
        load_raw_archive(zpath)


def test_non_netcdf_members_are_ignored(archive, tmp_path):
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr("README.txt", "hello")
    assert set(load_raw_archive(archive)) == {"skt", "p86.162", "u250"}


def test_duplicate_variables_across_members_raise(archive, tmp_path):
    p = tmp_path / "again_skt.nc"
    write_member(p, "skt", 1.0)
    with zipfile.ZipFile(archive, "a") as z:
        z.write(p, "skin_temperature_again.nc")
    with pytest.raises(ValueError, match="duplicate"):
        load_raw_archive(archive)
