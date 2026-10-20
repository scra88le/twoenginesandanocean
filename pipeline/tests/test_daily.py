import csv
import json
from datetime import UTC, date, datetime

import numpy as np
import pytest
from _helpers import make_multiday_archive, synthetic_tidy

from pipeline import run
from pipeline.daily import run_daily
from pipeline.deploy import upload
from pipeline.encode import scalar_png
from pipeline.points import build_series, read_series
from pipeline.publish import publish_date
from pipeline.store import LocalStore

D1, D2, D3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)


class FakeCds:
    """CDS as far as the daily job sees it: the newest date, requests and their statuses."""

    def __init__(self, tmp, latest=D3):
        self.latest, self.tmp, self.statuses, self.requests, self.n = latest, tmp, {}, {}, 0

    def check_authentication(self):
        pass

    def get_collection(self, _id):
        class Col:
            end_datetime = datetime(2000, 1, 1, tzinfo=UTC)

        Col.end_datetime = datetime(*self.latest.timetuple()[:3], tzinfo=UTC)
        return Col()

    def submit(self, _collection, request):
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
                return make_multiday_archive(target, {"skt_x.nc": ("skt", 280.0)}, ds, client.tmp)

        return Remote()


def seed_site(tmp_path, dates):
    """A published site holding `dates`, built from synthetic tidy data, in a local bucket."""
    out, raw, work = tmp_path / "seed-out", tmp_path / "seed-raw", tmp_path / "seed-work"
    work.mkdir()
    for d in dates:
        ds = synthetic_tidy(tsr=240.0)
        ds.attrs["date"] = d.isoformat()
        ds.to_netcdf(work / f"tidy_{d}.nc")
        assert run.build_date(d, raw, work, out) == []
    build_series(out)
    store = LocalStore(tmp_path / "bucket")
    upload(store, out)
    return store


def dirs(tmp_path, name):
    return tmp_path / f"{name}-raw", tmp_path / f"{name}-work", tmp_path / f"{name}-out"


def add_tidy(work, d, **overrides):
    work.mkdir(parents=True, exist_ok=True)
    ds = synthetic_tidy(**{"tsr": 240.0, **overrides})
    ds.attrs["date"] = d.isoformat()
    ds.to_netcdf(work / f"tidy_{d}.nc")


def snapshot(store):
    return {k: (i.size, i.md5) for k, i in store.list().items()}


def test_a_new_date_is_built_and_published_with_everything_that_depends_on_it(tmp_path):
    store = seed_site(tmp_path, [D1, D2])
    raw, work, out = dirs(tmp_path, "day")
    add_tidy(work, D3)
    cds = FakeCds(tmp_path)
    logs = []
    result = run_daily(
        store, cds, raw, work, out, days=3, log=logs.append, fetch=lambda c, d, r: []
    )
    assert result.built == [D3] and result.failed == {} and result.uploaded is not None
    keys = set(store.list())
    assert {f"fields/{D3}/olr.png", f"fields/{D3}/wind10_uv.png", f"points/{D3}/0_0.bin"} <= keys
    manifest = json.loads((tmp_path / "bucket" / "manifest.json").read_text())
    assert manifest["dates"] == [D1.isoformat(), D2.isoformat(), D3.isoformat()]
    dates, codes = read_series((tmp_path / "bucket" / "series" / "olr" / "0_0.bin").read_bytes())
    assert dates == manifest["dates"]  # the series was rebuilt from the downloaded maps
    rows = list(csv.DictReader((tmp_path / "bucket" / "logs" / "global_means.csv").open()))
    assert [r["date"] for r in rows] == manifest["dates"] and {r["status"] for r in rows} == {"ok"}
    assert not [k for k in keys if k.endswith(".tmp") or k.endswith(".part")]
    assert any("manifest published (3 dates)" in m for m in logs)


def test_bad_credentials_fail_before_anything_is_downloaded_or_changed(tmp_path):
    store = seed_site(tmp_path, [D1, D2])
    before = snapshot(store)
    raw, work, out = dirs(tmp_path, "bad")

    class Denied(FakeCds):
        def check_authentication(self):  # what a bad key does, as measured against CDS
            raise PermissionError("401 Client Error: Unauthorized (bad CDS key)")

        def get_collection(self, _id):  # CDS answers this without a key
            return super().get_collection(_id)

    with pytest.raises(PermissionError, match="Unauthorized"):
        run_daily(store, Denied(tmp_path), raw, work, out, days=3)
    assert snapshot(store) == before  # yesterday's site, byte for byte
    assert not out.exists()  # and the run didn't even start downloading


def test_a_crash_while_building_leaves_the_site_alone_but_keeps_the_submitted_requests(tmp_path):
    store = seed_site(tmp_path, [D1, D2])
    before = snapshot(store)
    raw, work, out = dirs(tmp_path, "crash")
    raw.mkdir(parents=True)
    (raw / "pending.json").write_text(
        '{"q": {"id": "1", "name": "single_mean", "days": ["2026-10-03"]}}'
    )

    def boom(*a, **k):
        raise MemoryError("out of memory while building")

    add_tidy(work, D3)
    with pytest.raises(MemoryError):
        run_daily(
            store, FakeCds(tmp_path), raw, work, out, days=3, fetch=lambda c, d, r: [], build=boom
        )
    after = snapshot(store)
    assert {k: v for k, v in after.items() if k != "state/pending.json"} == before
    assert "state/pending.json" in after  # the request IDs were saved


def test_a_date_that_fails_validation_is_skipped_and_logged_and_the_rest_still_published(tmp_path):
    store = seed_site(tmp_path, [D1])
    raw, work, out = dirs(tmp_path, "val")
    add_tidy(work, D2, tsr=300.0)  # a global mean far outside 220-260 W m-2
    add_tidy(work, D3)
    result = run_daily(store, FakeCds(tmp_path), raw, work, out, days=3, fetch=lambda c, d, r: [])
    assert result.built == [D3]
    assert list(result.failed) == [D2] and "tsr" in result.failed[D2][0]
    manifest = json.loads((tmp_path / "bucket" / "manifest.json").read_text())
    assert manifest["dates"] == [D1.isoformat(), D3.isoformat()]  # D2 is not published
    assert f"fields/{D2}/olr.png" not in store.list()
    rows = {
        r["date"]: r["status"]
        for r in csv.DictReader((tmp_path / "bucket" / "logs" / "global_means.csv").open())
    }
    assert rows == {D1.isoformat(): "ok", D2.isoformat(): "failed", D3.isoformat(): "ok"}


def test_nothing_new_changes_nothing_in_the_store_but_the_request_state(tmp_path):
    store = seed_site(tmp_path, [D1, D2, D3])
    before = snapshot(store)
    raw, work, out = dirs(tmp_path, "idle")
    result = run_daily(store, FakeCds(tmp_path), raw, work, out, days=3, fetch=lambda c, d, r: [])
    assert result.built == [] and result.uploaded is None
    assert snapshot(store) == before


def test_requests_survive_between_runs_until_their_dates_are_published(tmp_path):
    store = seed_site(tmp_path, [D1, D2])
    cds = FakeCds(tmp_path)

    def publish_fake(day, raw_dir, work_dir, out_dir):
        """Stands in for the build: needs the raw archives collected from CDS to be there."""
        for name in ("single_mean", "single_sum", "pressure_mean"):
            assert (raw_dir / f"{name}_{day}.nc").is_file(), f"{name} archive missing for {day}"
        files = {"olr.png": scalar_png(np.full((360, 720), 2, dtype=np.uint16))}
        publish_date(out_dir, day.isoformat(), files, points={"0_0.bin": b"p"})
        return []

    # Run 1: nothing is there yet, so the three requests for the new date are submitted.
    raw, work, out = dirs(tmp_path, "r1")
    r1 = run_daily(store, cds, raw, work, out, days=1, build=publish_fake)
    assert cds.n == 3 and r1.built == [] and len(r1.pending) == 3 and r1.uploaded is None
    state = json.loads((tmp_path / "bucket" / "state" / "pending.json").read_text())
    assert sorted(j["name"] for j in state.values()) == [
        "pressure_mean",
        "single_mean",
        "single_sum",
    ]

    # Run 2, on a fresh machine: still queued at CDS, so nothing is submitted again.
    raw, work, out = dirs(tmp_path, "r2")
    r2 = run_daily(store, cds, raw, work, out, days=1, build=publish_fake)
    assert cds.n == 3 and r2.built == [] and len(r2.pending) == 3

    # Run 3: two of three are done. Their archives are collected, but the date can't be built,
    # and on a fresh machine they'd be gone, so the requests must still be remembered.
    cds.statuses["r1"] = cds.statuses["r2"] = "successful"
    raw, work, out = dirs(tmp_path, "r3")
    r3 = run_daily(store, cds, raw, work, out, days=1, build=publish_fake)
    assert r3.built == [] and cds.n == 3
    assert len(json.loads((tmp_path / "bucket" / "state" / "pending.json").read_text())) == 3

    # Run 4: all done. The collected archives complete the date, it is published, and the
    # requests are forgotten.
    cds.statuses["r3"] = "successful"
    raw, work, out = dirs(tmp_path, "r4")
    r4 = run_daily(store, cds, raw, work, out, days=1, build=publish_fake)
    assert r4.built == [D3] and r4.uploaded is not None
    assert (
        json.loads((tmp_path / "bucket" / "manifest.json").read_text())["dates"][-1]
        == D3.isoformat()
    )
    assert json.loads((tmp_path / "bucket" / "state" / "pending.json").read_text()) == {}
