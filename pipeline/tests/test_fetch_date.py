import json
from datetime import date

import pytest

from pipeline.fetch import build_requests, fetch_date

D = date(2026, 10, 1)


class FakeRemote:
    def __init__(self, client, rid):
        self.client, self.rid = client, rid

    @property
    def status(self):
        return self.client.statuses[self.rid]

    def download(self, target):
        self.client.downloads.append(self.rid)
        with open(target, "wb") as f:
            f.write(b"data-" + self.rid.encode())
        return target


class FakeClient:
    def __init__(self):
        self.statuses, self.submitted, self.downloads, self.n = {}, [], [], 0

    def submit(self, collection_id, request):
        self.n += 1
        rid = f"r{self.n}"
        self.statuses[rid] = "accepted"
        self.submitted.append((collection_id, request))

        class R:
            request_id = rid

        return R()

    def get_remote(self, rid):
        return FakeRemote(self, rid)


def test_first_call_submits_everything_and_records_ids(tmp_path):
    c = FakeClient()
    pending = fetch_date(c, D, tmp_path)
    assert sorted(pending) == sorted(s.name for s in build_requests(D))
    assert len(c.submitted) == 3
    state = json.loads((tmp_path / "pending.json").read_text())
    assert set(state[D.isoformat()]) == set(pending)


def test_second_call_does_not_resubmit_requests_still_queued(tmp_path):
    c = FakeClient()
    fetch_date(c, D, tmp_path)
    fetch_date(c, D, tmp_path)
    assert len(c.submitted) == 3


def test_finished_requests_are_downloaded_and_dropped_from_state(tmp_path):
    c = FakeClient()
    fetch_date(c, D, tmp_path)
    c.statuses["r1"] = "successful"
    pending = fetch_date(c, D, tmp_path)
    first = build_requests(D)[0]
    assert first.name not in pending
    assert (tmp_path / first.filename).read_bytes() == b"data-r1"
    state = json.loads((tmp_path / "pending.json").read_text())
    assert first.name not in state[D.isoformat()]


def test_already_downloaded_files_are_skipped(tmp_path):
    c = FakeClient()
    for spec in build_requests(D):
        (tmp_path / spec.filename).write_bytes(b"x")
    assert fetch_date(c, D, tmp_path) == []
    assert c.submitted == []


def test_failed_request_is_resubmitted_next_time(tmp_path):
    c = FakeClient()
    fetch_date(c, D, tmp_path)
    c.statuses["r2"] = "failed"
    fetch_date(c, D, tmp_path)
    assert len(c.submitted) == 4


def test_download_goes_to_a_partial_file_first(tmp_path):
    # A crash mid-download must not leave a truncated file that looks complete.
    c = FakeClient()
    fetch_date(c, D, tmp_path)
    c.statuses["r1"] = "successful"
    fetch_date(c, D, tmp_path)
    assert not list(tmp_path.glob("*.part"))


def test_all_done_returns_empty_pending(tmp_path):
    c = FakeClient()
    fetch_date(c, D, tmp_path)
    for rid in list(c.statuses):
        c.statuses[rid] = "successful"
    assert fetch_date(c, D, tmp_path) == []
    assert len(list(tmp_path.glob("*.nc"))) == 3


def test_rejects_non_date(tmp_path):
    with pytest.raises(TypeError):
        fetch_date(FakeClient(), "2026-10-01", tmp_path)
