import hashlib

import pytest
from _store_helpers import FakeS3

from pipeline import store as st


def test_cache_rules_never_cache_the_manifest_and_cache_data_for_an_hour():
    assert st.cache_control("manifest.json") == "no-cache"
    assert st.cache_control("state/pending.json") == "no-store"
    assert st.cache_control("logs/global_means.csv") == "no-cache"
    assert st.cache_control("fields/2026-10-01/olr.png") == "public, max-age=3600"
    assert st.cache_control("points/2026-10-01/0_0.bin") == "public, max-age=3600"
    assert st.cache_control("series/olr/0_0.bin") == "public, max-age=3600"
    assert st.cache_control("clim/01/olr.png") == "public, max-age=86400"
    assert st.cache_control("something/else") == "no-cache"  # unknown things are never stale


def test_content_types():
    assert st.content_type("manifest.json") == "application/json"
    assert st.content_type("fields/d/olr.png") == "image/png"
    assert st.content_type("series/olr/0_0.bin") == "application/octet-stream"
    assert st.content_type("logs/global_means.csv") == "text/csv"


def test_local_store_round_trip(tmp_path):
    s = st.LocalStore(tmp_path / "bucket")
    src = tmp_path / "f.png"
    src.write_bytes(b"hello")
    s.put("fields/d/a.png", src)
    s.put("series/x.bin", src)
    assert s.list("fields/") == {
        "fields/d/a.png": st.ObjectInfo(5, hashlib.md5(b"hello").hexdigest())
    }
    assert set(s.list()) == {"fields/d/a.png", "series/x.bin"}
    assert s.get("fields/d/a.png", tmp_path / "got" / "a.png") is True
    assert (tmp_path / "got" / "a.png").read_bytes() == b"hello"
    assert s.get("nope", tmp_path / "x") is False
    s.delete(["fields/d/a.png", "missing"])
    assert set(s.list()) == {"series/x.bin"}
    assert not list((tmp_path / "bucket").rglob("*.tmp"))  # writes go through a partial file


def test_local_store_refuses_keys_that_escape_the_root(tmp_path):
    s = st.LocalStore(tmp_path / "bucket")
    src = tmp_path / "f"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        s.put("../outside", src)


def test_s3_store_uses_the_prefix_headers_and_pages():
    client = FakeS3()
    s = st.S3Store(client, "bkt", "/data/")
    assert s.prefix == "data/"
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        for i in range(5):
            f = pathlib.Path(d) / f"{i}"
            f.write_bytes(b"x" * (i + 1))
            s.put(f"fields/2026-10-01/{i}.png", f)
        s.put("manifest.json", pathlib.Path(d) / "0")
        dest = pathlib.Path(d) / "got.png"
        assert s.get("fields/2026-10-01/3.png", dest) is True and dest.read_bytes() == b"x" * 4
        assert s.get("fields/none.png", pathlib.Path(d) / "n") is False
    assert client.objects[("bkt", "data/manifest.json")]["cache"] == "no-cache"
    assert client.objects[("bkt", "data/fields/2026-10-01/0.png")]["type"] == "image/png"
    listing = s.list("fields/")
    assert sorted(listing) == [
        f"fields/2026-10-01/{i}.png" for i in range(5)
    ]  # prefix stripped, 3 pages
    assert listing["fields/2026-10-01/2.png"] == st.ObjectInfo(3, hashlib.md5(b"xxx").hexdigest())


def test_s3_store_deletes_in_batches_of_a_thousand():
    client = FakeS3()
    s = st.S3Store(client, "bkt")
    keys = [f"fields/d/{i}.png" for i in range(2500)]
    for k in keys:
        client.objects[("bkt", k)] = {"body": b"x", "type": "", "cache": ""}
    s.delete(keys)
    assert client.delete_calls == [1000, 1000, 500]
    assert not client.objects


def test_open_store_understands_file_and_s3_urls(tmp_path):
    assert isinstance(st.open_store(f"file://{tmp_path}"), st.LocalStore)
    s = st.open_store("s3://my-bucket/sub/dir", client=FakeS3())
    assert isinstance(s, st.S3Store) and s.bucket == "my-bucket" and s.prefix == "sub/dir/"
    assert st.open_store("s3://my-bucket", client=FakeS3()).prefix == ""
    for bad in ("my-bucket", "https://example.com/x", "s3://"):
        with pytest.raises(ValueError):
            st.open_store(bad)
