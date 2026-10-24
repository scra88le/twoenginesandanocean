import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
import xarray as xr
from _helpers import make_multiday_archive, synthetic_tidy

from pipeline.lw_backfill import (
    add_lw_up,
    dates_needing_lw_up,
    fetch_str,
    str_request,
)
from pipeline.tidy import write_tidy

SECONDS = 86_400


def days(start, n):
    return [start + timedelta(days=k) for k in range(n)]


class FakeClient:
    """Finishes whatever it is given; the archive holds `str` = -value J m-2 per day."""

    def __init__(self, workdir, value=60.0, plain=False):
        self.workdir, self.value, self.plain = workdir, value, plain
        self.statuses, self.requests, self.n = {}, {}, 0

    def submit(self, collection_id, request):
        self.n += 1
        rid = f"r{self.n}"
        self.statuses[rid], self.requests[rid] = "accepted", (collection_id, request)

        class R:
            request_id = rid

        return R()

    def get_remote(self, rid):
        client = self

        class Remote:
            @property
            def status(self):
                return client.statuses[rid]

            def download(self, target):
                _, r = client.requests[rid]
                ds = [date(int(r["year"]), int(r["month"]), int(d)) for d in r["day"]]
                zipped = make_multiday_archive(
                    client.workdir / "made.zip",
                    {"str_x.nc": ("str", -client.value * SECONDS)},
                    ds,
                    client.workdir,
                )
                if not client.plain:
                    return zipped.replace(target)
                # a single-variable request comes back as a bare NetCDF file, not a zip
                with zipfile.ZipFile(zipped) as z:
                    return Path(target).write_bytes(z.read("str_x.nc"))

        return Remote()


@pytest.fixture
def client(tmp_path):
    w = tmp_path / "w"
    w.mkdir()
    return FakeClient(w)


# ---- the request -----------------------------------------------------------------------


def test_request_asks_for_surface_net_thermal_radiation_as_a_daily_sum():
    spec = str_request(days(date(2026, 9, 28), 3))
    assert spec.collection_id == "derived-era5-single-levels-daily-statistics"
    r = spec.request
    assert r["variable"] == ["surface_net_thermal_radiation"]
    assert r["daily_statistic"] == "daily_sum"
    assert (r["year"], r["month"], r["day"]) == ("2026", "09", ["28", "29", "30"])
    assert (r["time_zone"], r["frequency"]) == ("utc+00:00", "1_hourly")
    assert spec.filename == "single_str_2026-09-28_2026-09-30.nc"


def test_request_stays_within_the_cds_cost_limit():
    spec = str_request(days(date(2026, 8, 1), 31))
    assert len(spec.request["variable"]) * len(spec.request["day"]) <= 400


def test_request_rejects_a_chunk_spanning_months():
    with pytest.raises(ValueError):
        str_request([date(2026, 7, 31), date(2026, 8, 1)])


# ---- fetching --------------------------------------------------------------------------


def test_one_request_per_month_oldest_first_and_capped(tmp_path, client):
    raw = tmp_path / "raw"
    pending = fetch_str(client, days(date(2026, 7, 20), 90), raw, max_queued=2)
    assert pending == [
        "single_str_2026-07-20_2026-07-31.nc",
        "single_str_2026-08-01_2026-08-31.nc",
    ]
    assert len(client.requests) == 2


def test_queued_requests_are_not_resubmitted(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_str(client, days(date(2026, 8, 1), 3), raw)
    fetch_str(client, days(date(2026, 8, 1), 3), raw)
    assert len(client.requests) == 1


def test_it_leaves_the_daily_fetch_state_alone(tmp_path, client):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "pending.json").write_text("{}")
    fetch_str(client, days(date(2026, 8, 1), 3), raw)
    assert (raw / "pending.json").read_text() == "{}"
    assert not list(raw.glob("single_sum*"))


def test_finished_requests_become_date_archives_and_free_the_queue(tmp_path, client):
    raw = tmp_path / "raw"
    ds = days(date(2026, 7, 30), 4)  # two months, so two requests, both within the cap
    fetch_str(client, ds, raw, max_queued=2)
    for rid in client.statuses:
        client.statuses[rid] = "successful"
    assert fetch_str(client, ds, raw, max_queued=2) == []
    for d in ds:
        assert (raw / "lw" / f"single_str_{d}.nc").is_file()
    assert json.loads((raw / "lw" / "pending.json").read_text()) == {}
    assert len(client.requests) == 2


def test_a_failed_request_is_resubmitted(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_str(client, [date(2026, 8, 1)], raw)
    client.statuses["r1"] = "failed"
    fetch_str(client, [date(2026, 8, 1)], raw)
    assert len(client.requests) == 2


def test_dates_already_on_disk_are_not_requested(tmp_path, client):
    raw = tmp_path / "raw"
    (raw / "lw").mkdir(parents=True)
    (raw / "lw" / "single_str_2026-08-01.nc").write_bytes(b"x")
    assert fetch_str(client, [date(2026, 8, 1)], raw) == []
    assert client.requests == {}


# ---- adding lw_up to a tidy file -------------------------------------------------------


def _tidy_without_lw(work, day):
    ds = synthetic_tidy()
    ds.attrs["date"] = day.isoformat()
    write_tidy(ds, work)


def _archive(raw, day, value=60.0, tmp=None):
    (raw / "lw").mkdir(parents=True, exist_ok=True)
    return make_multiday_archive(
        raw / "lw" / f"single_str_{day}.nc", {"str_x.nc": ("str", -value * SECONDS)}, [day], tmp
    )


def test_dates_needing_lw_up_lists_tidy_files_without_it(tmp_path):
    work = tmp_path / "work"
    _tidy_without_lw(work, date(2026, 8, 1))
    _tidy_without_lw(work, date(2026, 8, 2))
    assert add_lw_up(date(2026, 8, 2), tmp_path / "none", work) is False  # no archive yet
    assert dates_needing_lw_up(work) == [date(2026, 8, 1), date(2026, 8, 2)]


def test_lw_up_is_the_sign_flipped_flux_in_w_m2(tmp_path):
    work, raw = tmp_path / "work", tmp_path / "raw"
    day = date(2026, 8, 1)
    _tidy_without_lw(work, day)
    _archive(raw, day, value=60.0, tmp=tmp_path)
    assert add_lw_up(day, raw, work) is True
    ds = xr.load_dataset(work / "tidy_2026-08-01.nc")
    # ECMWF's net thermal is negative (a loss); lw_up is positive upward, in W m-2
    assert float(ds["lw_up"].mean()) == pytest.approx(60.0, rel=1e-5)
    assert ds["lw_up"].attrs["sign"] == "positive upward"
    assert dates_needing_lw_up(work) == []


def test_other_fields_and_attributes_are_untouched(tmp_path):
    work, raw = tmp_path / "work", tmp_path / "raw"
    day = date(2026, 8, 1)
    _tidy_without_lw(work, day)
    before = xr.load_dataset(work / "tidy_2026-08-01.nc")
    _archive(raw, day, tmp=tmp_path)
    add_lw_up(day, raw, work)
    after = xr.load_dataset(work / "tidy_2026-08-01.nc")
    assert after.attrs == before.attrs
    for name in before.data_vars:
        xr.testing.assert_equal(after[name], before[name])


def test_a_date_that_has_lw_up_is_left_alone(tmp_path):
    work, raw = tmp_path / "work", tmp_path / "raw"
    day = date(2026, 8, 1)
    _tidy_without_lw(work, day)
    _archive(raw, day, value=60.0, tmp=tmp_path)
    add_lw_up(day, raw, work)
    _archive(raw, day, value=99.0, tmp=tmp_path)  # would change it if it were read again
    assert add_lw_up(day, raw, work) is False
    assert float(xr.load_dataset(work / "tidy_2026-08-01.nc")["lw_up"].mean()) == pytest.approx(
        60.0, rel=1e-5
    )


def test_an_implausible_global_mean_is_refused_and_changes_nothing(tmp_path):
    work, raw = tmp_path / "work", tmp_path / "raw"
    day = date(2026, 8, 1)
    _tidy_without_lw(work, day)
    _archive(raw, day, value=600.0, tmp=tmp_path)  # e.g. a units or sign mistake
    with pytest.raises(ValueError, match="lw_up"):
        add_lw_up(day, raw, work)
    assert "lw_up" not in xr.load_dataset(work / "tidy_2026-08-01.nc")


def test_a_single_variable_result_comes_back_as_a_bare_netcdf_not_a_zip(tmp_path):
    """Seen on the real CDS (2026-10-24): one variable gives a plain NetCDF file."""
    w = tmp_path / "w"
    w.mkdir()
    client = FakeClient(w, plain=True)
    raw = tmp_path / "raw"
    ds = days(date(2026, 8, 1), 2)
    fetch_str(client, ds, raw)
    for rid in client.statuses:
        client.statuses[rid] = "successful"
    assert fetch_str(client, ds, raw) == []
    for d in ds:
        assert (raw / "lw" / f"single_str_{d}.nc").is_file()
    from pipeline.load import load_raw_archive

    got = load_raw_archive(raw / "lw" / "single_str_2026-08-02.nc")
    assert float(got["str"][0, 0]) == -60.0 * SECONDS + 1.0  # the helper adds 1 per day
