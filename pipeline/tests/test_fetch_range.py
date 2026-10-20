import json
import zipfile
from datetime import date, timedelta

import pytest
from _helpers import make_multiday_archive

from pipeline.fetch import build_chunk_requests, chunk_dates, fetch_dates, split_archive
from pipeline.load import load_raw_archive


def days(start, n):
    return [start + timedelta(days=k) for k in range(n)]


# ---- chunking --------------------------------------------------------------------------


def test_consecutive_days_in_one_month_are_one_chunk():
    assert chunk_dates(days(date(2026, 8, 1), 31)) == [days(date(2026, 8, 1), 31)]


def test_chunks_split_at_month_boundaries_and_gaps():
    ds = days(date(2026, 7, 30), 4) + [date(2026, 8, 10)]  # Jul 30, 31, Aug 1, 2, Aug 10
    assert chunk_dates(ds) == [
        [date(2026, 7, 30), date(2026, 7, 31)],
        [date(2026, 8, 1), date(2026, 8, 2)],
        [date(2026, 8, 10)],
    ]


def test_chunking_sorts_and_removes_duplicates():
    assert chunk_dates([date(2026, 8, 2), date(2026, 8, 1), date(2026, 8, 2)]) == [
        [date(2026, 8, 1), date(2026, 8, 2)]
    ]


def test_chunk_requests_list_the_days():
    specs = build_chunk_requests(days(date(2026, 9, 28), 3))
    assert {s.name for s in specs} == {"single_mean", "single_sum", "pressure_mean"}
    for s in specs:
        assert (s.request["year"], s.request["month"]) == ("2026", "09")
        assert s.request["day"] == ["28", "29", "30"]
        assert s.filename == f"{s.name}_2026-09-28_2026-09-30.nc"


def test_chunk_requests_stay_within_the_cds_cost_limit():
    # cost = variables x days; the limit is 400 per request
    for s in build_chunk_requests(days(date(2026, 8, 1), 31)):
        assert len(s.request["variable"]) * len(s.request["day"]) <= 400


def test_chunk_requests_reject_a_chunk_spanning_months():
    with pytest.raises(ValueError):
        build_chunk_requests([date(2026, 7, 31), date(2026, 8, 1)])


# ---- splitting -------------------------------------------------------------------------


def test_split_writes_one_archive_per_date(tmp_path):
    ds = days(date(2026, 8, 1), 3)
    src = make_multiday_archive(
        tmp_path / "chunk.nc",
        {"skt_x.nc": ("skt", 280.0), "tcwv_x.nc": ("tcwv", 20.0)},
        ds,
        tmp_path,
    )
    raw = tmp_path / "raw"
    written = split_archive(src, "single_mean", raw)
    assert [p.name for p in written] == [f"single_mean_{d}.nc" for d in ds]
    second = load_raw_archive(raw / "single_mean_2026-08-02.nc")
    assert float(second["skt"][0, 0]) == 281.0 and float(second["tcwv"][0, 0]) == 21.0
    with zipfile.ZipFile(raw / "single_mean_2026-08-02.nc") as z:
        assert sorted(z.namelist()) == ["skt_x.nc", "tcwv_x.nc"]
    assert not list(raw.glob("*.part"))


def test_split_leaves_existing_date_archives_alone(tmp_path):
    ds = days(date(2026, 8, 1), 2)
    src = make_multiday_archive(tmp_path / "chunk.nc", {"skt_x.nc": ("skt", 280.0)}, ds, tmp_path)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "single_mean_2026-08-01.nc").write_bytes(b"keep")
    split_archive(src, "single_mean", raw)
    assert (raw / "single_mean_2026-08-01.nc").read_bytes() == b"keep"


# ---- fetch_dates with a fake client ----------------------------------------------------


class FakeClient:
    def __init__(self, workdir):
        self.workdir, self.statuses, self.requests, self.n = workdir, {}, {}, 0

    def submit(self, collection_id, request):
        self.n += 1
        rid = f"r{self.n}"
        self.statuses[rid], self.requests[rid] = "accepted", request

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
                r = client.requests[rid]
                ds = [date(int(r["year"]), int(r["month"]), int(d)) for d in r["day"]]
                return make_multiday_archive(
                    target, {"skt_x.nc": ("skt", 280.0)}, ds, client.workdir
                )

        return Remote()


@pytest.fixture
def client(tmp_path):
    w = tmp_path / "w"
    w.mkdir()
    return FakeClient(w)


def test_first_call_submits_one_request_per_statistic_per_chunk(tmp_path, client):
    raw = tmp_path / "raw"
    pending = fetch_dates(client, days(date(2026, 7, 30), 4), raw, max_queued=10)  # two chunks
    assert len(client.requests) == 6 and len(pending) == 6
    state = json.loads((raw / "pending.json").read_text())
    covered = sorted(d for v in state.values() if v["name"] == "single_mean" for d in v["days"])
    assert covered == ["2026-07-30", "2026-07-31", "2026-08-01", "2026-08-02"]


def test_queued_requests_are_not_resubmitted(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_dates(client, days(date(2026, 8, 1), 3), raw)
    fetch_dates(client, days(date(2026, 8, 1), 3), raw)
    assert len(client.requests) == 3


def test_a_new_day_is_requested_without_repeating_queued_ones(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_dates(client, days(date(2026, 8, 1), 3), raw, max_queued=10)
    fetch_dates(client, days(date(2026, 8, 1), 4), raw, max_queued=10)  # one more day
    assert len(client.requests) == 6
    assert [r["day"] for r in list(client.requests.values())[3:]] == [["04"]] * 3


def test_finished_requests_are_split_into_date_archives(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_dates(client, days(date(2026, 8, 1), 2), raw)
    for rid in client.statuses:
        client.statuses[rid] = "successful"
    assert fetch_dates(client, days(date(2026, 8, 1), 2), raw) == []
    for name in ("single_mean", "single_sum", "pressure_mean"):
        for d in ("2026-08-01", "2026-08-02"):
            assert (raw / f"{name}_{d}.nc").is_file()
    assert not list(raw.glob("*_2026-08-01_2026-08-02.nc"))  # chunk archive removed after split
    assert json.loads((raw / "pending.json").read_text()) == {}


def test_failed_requests_are_resubmitted(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_dates(client, [date(2026, 8, 1)], raw)
    client.statuses["r1"] = "failed"
    fetch_dates(client, [date(2026, 8, 1)], raw)
    assert len(client.requests) == 4


def test_dates_already_on_disk_are_not_requested(tmp_path, client):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("single_mean", "single_sum", "pressure_mean"):
        (raw / f"{name}_2026-08-01.nc").write_bytes(b"x")
    assert fetch_dates(client, [date(2026, 8, 1)], raw) == []
    assert client.requests == {}


def test_queued_requests_are_capped_per_dataset_oldest_dates_first(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_dates(client, days(date(2026, 7, 1), 92), raw, max_queued=2)  # July to September
    by_name = {}
    for k in json.loads((raw / "pending.json").read_text()):
        by_name.setdefault(k.split("_2026")[0], []).append(k)
    # both single-level statistics for July (so July can complete), pressure July and August
    assert by_name == {
        "single_mean": ["single_mean_2026-07-01_2026-07-31.nc"],
        "single_sum": ["single_sum_2026-07-01_2026-07-31.nc"],
        "pressure_mean": [
            "pressure_mean_2026-07-01_2026-07-31.nc",
            "pressure_mean_2026-08-01_2026-08-31.nc",
        ],
    }


def test_rejected_requests_make_room_for_the_next(tmp_path, client):
    raw = tmp_path / "raw"
    ds = days(date(2026, 7, 1), 62)
    fetch_dates(client, ds, raw, max_queued=2)
    for rid in client.statuses:
        client.statuses[rid] = "rejected"
    fetch_dates(client, ds, raw, max_queued=2)
    assert len(client.requests) == 8  # the same four again, not more


# ---- keep_collected: for a job whose raw directory vanishes after every run ---------------


def test_keep_collected_leaves_finished_requests_in_the_state(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_dates(client, days(date(2026, 8, 1), 2), raw)
    for rid in client.statuses:
        client.statuses[rid] = "successful"
    pending = fetch_dates(client, days(date(2026, 8, 1), 2), raw, keep_collected=True)
    assert len(pending) == 3  # still remembered, though collected
    assert (raw / "single_mean_2026-08-02.nc").is_file()  # and its archives are there to build from
    assert len(client.requests) == 3  # nothing was submitted again
    # on a fresh machine the same state collects the same archives again
    state = (raw / "pending.json").read_text()
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "pending.json").write_text(state)
    fetch_dates(client, days(date(2026, 8, 1), 2), fresh, keep_collected=True)
    assert (fresh / "pressure_mean_2026-08-01.nc").is_file() and len(client.requests) == 3


def test_an_expired_result_is_forgotten_and_requested_again(tmp_path, client):
    raw = tmp_path / "raw"
    fetch_dates(client, [date(2026, 8, 1)], raw)
    client.statuses["r1"] = "successful"

    class Gone(Exception):
        pass

    original = client.get_remote
    broken = {"r1"}

    def expired(rid):
        remote = original(rid)
        if rid in broken:

            def fail(target):
                raise Gone("results have expired")

            remote.download = fail
        return remote

    client.get_remote = expired
    fetch_dates(client, [date(2026, 8, 1)], raw, keep_collected=True)
    assert len(client.requests) == 4  # r1's statistic was requested again
    # without keep_collected the failure is not hidden
    raw2 = tmp_path / "raw2"
    fetch_dates(client, [date(2026, 8, 5)], raw2)
    broken.add("r5")
    client.statuses["r5"] = "successful"
    with pytest.raises(Gone):
        fetch_dates(client, [date(2026, 8, 5)], raw2)
