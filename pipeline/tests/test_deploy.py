import json
from datetime import date

import pytest
from _store_helpers import RecordingStore, make_out

from pipeline import deploy
from pipeline.fetch import settle_state
from pipeline.store import LocalStore

D1, D2, D3 = "2026-10-01", "2026-10-02", "2026-10-03"


def test_everything_goes_up_and_the_manifest_goes_last(tmp_path):
    out = make_out(tmp_path / "out", [D1, D2])
    store = RecordingStore(tmp_path / "bucket")
    result = deploy.upload(store, out)
    assert store.puts[-1] == "manifest.json"
    assert store.puts.count("manifest.json") == 1
    files = [p for p in out.rglob("*") if p.is_file()]
    assert result.uploaded == len(files) and result.skipped == 0 and result.deleted == 0
    assert set(store.list()) == {p.relative_to(out).as_posix() for p in files}
    # data first, then series, then the log, then the manifest
    order = [k.split("/")[0] for k in store.puts]
    assert order.index("series") > max(
        i for i, k in enumerate(order) if k in ("fields", "points", "clim")
    )
    assert order.index("logs") > max(i for i, k in enumerate(order) if k == "series")


def test_unchanged_files_are_not_uploaded_again_and_changed_ones_are(tmp_path):
    out = make_out(tmp_path / "out", [D1, D2])
    store = RecordingStore(tmp_path / "bucket")
    deploy.upload(store, out)
    store.puts.clear()
    again = deploy.upload(store, out)
    assert store.puts == ["manifest.json"]  # the manifest is always written, nothing else
    assert again.uploaded == 1 and again.skipped > 10
    (out / "series" / "olr" / "0_0.bin").write_bytes(b"new series")
    store.puts.clear()
    deploy.upload(store, out)
    assert store.puts == ["series/olr/0_0.bin", "manifest.json"]


def test_dates_beyond_the_window_are_deleted_only_after_the_new_manifest(tmp_path):
    store = RecordingStore(tmp_path / "bucket")
    deploy.upload(store, make_out(tmp_path / "old", [D1, D2]))
    new = make_out(tmp_path / "new", [D2, D3], tag="b")
    store.deleted.clear()
    result = deploy.upload(store, new)
    assert sorted(store.deleted) == sorted(
        [f"fields/{D1}/{n}" for n in ("olr.png", "wind10.png", "wind10_uv.png", "olr_anom.png")]
        + [f"points/{D1}/0_0.bin"]
    )
    assert result.deleted == 5
    assert json.loads((tmp_path / "bucket" / "manifest.json").read_text())["dates"] == [D2, D3]
    assert not (tmp_path / "bucket" / "fields" / D1).exists()  # and no empty folder remains
    assert (tmp_path / "bucket" / "clim" / "01" / "olr.png").is_file()  # the climatology stays


def test_a_failure_before_the_manifest_leaves_the_published_site_untouched(tmp_path):
    old = make_out(tmp_path / "old", [D1, D2])
    new = make_out(tmp_path / "new", [D2, D3], tag="b")
    for n, failing in enumerate(
        ("series/olr/0_0.bin", f"points/{D3}/0_0.bin", "logs/global_means.csv")
    ):
        bucket = tmp_path / f"bucket{n}"  # a fresh published site for each failure point
        deploy.upload(RecordingStore(bucket), old)
        manifest_before = (bucket / "manifest.json").read_text()
        before = {k: (bucket / k).read_bytes() for k in LocalStore(bucket).list()}
        with pytest.raises(OSError, match="simulated"):
            deploy.upload(RecordingStore(bucket, fail_on=failing), new)
        assert (bucket / "manifest.json").read_text() == manifest_before
        # everything the old manifest points to is still there, unchanged
        for key in [f"fields/{D1}/olr.png", f"fields/{D2}/olr.png", f"points/{D1}/0_0.bin"]:
            assert (bucket / key).read_bytes() == before[key]
        assert (bucket / "fields" / D1).is_dir()  # nothing was deleted either


def test_nothing_to_publish_without_a_manifest(tmp_path):
    (tmp_path / "out").mkdir()
    with pytest.raises(FileNotFoundError, match="manifest"):
        deploy.upload(LocalStore(tmp_path / "bucket"), tmp_path / "out")


def test_download_state_brings_back_what_a_daily_run_needs(tmp_path):
    store = LocalStore(tmp_path / "bucket")
    deploy.upload(store, make_out(tmp_path / "src", [D1, D2]))
    (tmp_path / "pending-src").mkdir()
    (tmp_path / "pending-src" / "pending.json").write_text('{"x": 1}')
    assert deploy.upload_state(store, tmp_path / "pending-src") is True
    raw, out = tmp_path / "raw", tmp_path / "out"
    manifest = deploy.download_state(store, raw, out)
    assert manifest["dates"] == [D1, D2]
    got = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert got == {
        "manifest.json", "logs/global_means.csv", "clim/clim.json", "clim/01/olr.png",
        "clim/02/olr.png",
        *(f"fields/{d}/{lid}.png" for d in (D1, D2) for lid in ("olr", "wind10")),
    }  # fmt: skip
    # not the vector, anomaly or point files, and not the chart's climatology tiles
    assert (raw / "pending.json").read_text() == '{"x": 1}'


def test_an_empty_store_means_starting_from_nothing(tmp_path):
    logs = []
    assert (
        deploy.download_state(
            LocalStore(tmp_path / "bucket"), tmp_path / "raw", tmp_path / "out", logs.append
        )
        is None
    )
    assert any("no manifest" in m for m in logs)


def test_state_is_saved_only_when_there_is_some(tmp_path):
    store = LocalStore(tmp_path / "bucket")
    (tmp_path / "raw").mkdir()
    assert deploy.upload_state(store, tmp_path / "raw") is False
    assert "state/pending.json" not in store.list()


def test_settle_state_forgets_published_and_stale_requests(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    state = {
        "done.nc": {"id": "1", "name": "single_mean", "days": [D1, D2]},
        "partly.nc": {"id": "2", "name": "single_sum", "days": [D2, D3]},
        "old.nc": {"id": "3", "name": "single_sum", "days": ["2026-08-01"]},
    }
    (raw / "pending.json").write_text(json.dumps(state))
    dropped = settle_state(raw, {D1, D2}, date(2026, 10, 3))
    assert dropped == 2  # published, and older than 30 days
    assert list(json.loads((raw / "pending.json").read_text())) == ["partly.nc"]
    assert settle_state(raw, {D1, D2}, date(2026, 10, 3)) == 0
