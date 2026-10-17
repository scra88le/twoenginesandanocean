from datetime import date

import pytest
from _helpers import make_archive

from pipeline.tidy import build_tidy, write_tidy

D = date(2026, 10, 1)


@pytest.fixture
def raw_dir(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    work = tmp_path / "scratch"
    work.mkdir()
    make_archive(
        raw / "single_mean_2026-10-01.nc",
        {"skt_x.nc": ("skt", 288.0, False), "lsm_x.nc": ("lsm", 1.0, False)},
        work,
    )
    make_archive(
        raw / "single_sum_2026-10-01.nc",
        {"ttr_x.nc": ("ttr", -240.0 * 86_400, False)},
        work,
    )
    make_archive(raw / "pressure_mean_2026-10-01.nc", {"u_x.nc": ("u", 30.0, True)}, work)
    return raw


def test_build_tidy_combines_all_archives(raw_dir):
    ds = build_tidy(D, raw_dir)
    assert set(ds.data_vars) == {"skt", "lsm", "olr", "u250"}
    assert ds["olr"].shape == (360, 720)
    assert float(ds["olr"].mean()) == pytest.approx(240.0)
    assert ds.attrs["date"] == "2026-10-01"


def test_missing_archive_is_named_in_the_error(raw_dir):
    (raw_dir / "single_sum_2026-10-01.nc").unlink()
    with pytest.raises(FileNotFoundError, match="single_sum"):
        build_tidy(D, raw_dir)


def test_write_tidy_round_trips_and_is_atomic(raw_dir, tmp_path):
    import xarray as xr

    ds = build_tidy(D, raw_dir)
    out = write_tidy(ds, tmp_path / "work")
    assert out.name == "tidy_2026-10-01.nc"
    assert not list((tmp_path / "work").glob("*.part"))
    with xr.open_dataset(out) as back:
        assert float(back["olr"].mean()) == pytest.approx(240.0, rel=1e-6)
        assert back["olr"].dtype == "float32"
