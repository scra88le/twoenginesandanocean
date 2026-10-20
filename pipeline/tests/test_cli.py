import pytest

from pipeline.cli import build_parser


def test_build_requires_date_and_out():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["build"])


def test_backfill_defaults_to_90_days():
    args = build_parser().parse_args(["backfill", "--out", "./out"])
    assert args.days == 90


def test_fetch_and_tidy_parse_dates_and_dirs():
    p = build_parser()
    a = p.parse_args(["fetch", "--date", "2026-10-01"])
    assert str(a.date) == "2026-10-01" and str(a.raw) == "raw" and a.wait is False
    b = p.parse_args(["tidy", "--date", "2026-10-01", "--work", "w"])
    assert str(b.work) == "w" and str(b.raw) == "raw"


def test_bad_date_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["fetch", "--date", "2026-13-01"])


def test_tidy_reports_missing_archives(tmp_path, capsys):
    from pipeline.cli import main

    code = main(["tidy", "--date", "2026-10-01", "--raw", str(tmp_path), "--work", str(tmp_path)])
    assert code == 1
    assert "missing raw archives" in capsys.readouterr().err


def test_build_publishes_from_a_tidy_file(tmp_path, capsys):
    import json

    from _helpers import synthetic_tidy

    from pipeline.cli import main

    work, out = tmp_path / "work", tmp_path / "out"
    work.mkdir()
    synthetic_tidy(tsr=240.0).to_netcdf(work / "tidy_2026-10-01.nc")  # passes validation
    code = main(["build", "--date", "2026-10-01", "--work", str(work), "--out", str(out),
                 "--raw", str(tmp_path / "raw")])  # fmt: skip
    assert code == 0
    assert json.loads((out / "manifest.json").read_text())["dates"] == ["2026-10-01"]
    assert (out / "fields" / "2026-10-01" / "jet250_uv.png").is_file()


def test_build_without_raw_or_tidy_fails_cleanly(tmp_path, capsys):
    from pipeline.cli import main

    code = main(["build", "--date", "2026-10-01", "--work", str(tmp_path), "--out",
                 str(tmp_path / "out"), "--raw", str(tmp_path)])  # fmt: skip
    assert code == 1
    assert "missing raw archives" in capsys.readouterr().err
    assert not (tmp_path / "out" / "manifest.json").exists()


def _fake_daily(monkeypatch, failed):
    """Run the CLI's `daily` against a stub job, so only its wiring and exit code are tested."""
    from datetime import date

    import pipeline.daily as daily_mod
    import pipeline.fetch as fetch_mod
    import pipeline.store as store_mod

    seen = {}

    def run_daily(store, c, raw, work, out, days, log):
        seen.update(store=store, days=days, raw=raw, work=work, out=out)
        return daily_mod.DailyResult(date(2026, 10, 3), failed=failed)

    monkeypatch.setattr(daily_mod, "run_daily", run_daily)
    monkeypatch.setattr(fetch_mod, "client", lambda: object())
    monkeypatch.setattr(store_mod, "open_store", lambda url: f"store:{url}")
    return seen


def test_daily_needs_a_store(capsys, monkeypatch):
    from pipeline.cli import main

    monkeypatch.delenv("STORE_URL", raising=False)
    assert main(["daily"]) == 2
    assert "STORE_URL" in capsys.readouterr().err


def test_daily_succeeds_with_a_store_from_the_flag_or_the_environment(monkeypatch, capsys):
    from pipeline.cli import main

    seen = _fake_daily(monkeypatch, failed={})
    assert main(["daily", "--store", "s3://b/p", "--days", "4"]) == 0
    assert seen["store"] == "store:s3://b/p" and seen["days"] == 4 and str(seen["out"]) == "out"
    assert "built 0, failed 0" in capsys.readouterr().out
    monkeypatch.setenv("STORE_URL", "file:///tmp/x")
    assert build_parser().parse_args(["daily"]).store == "file:///tmp/x"


def test_daily_fails_the_run_when_a_date_failed_validation(monkeypatch, capsys):
    from datetime import date

    from pipeline.cli import main

    _fake_daily(monkeypatch, failed={date(2026, 10, 2): ["global mean tsr 300.00 outside 220-260"]})
    assert main(["daily", "--store", "file:///x"]) == 1
    assert (
        "::error::2026-10-02 not published" in capsys.readouterr().err
    )  # shows in the Actions log


def test_upload_publishes_a_data_root(tmp_path, capsys):
    from _store_helpers import make_out

    from pipeline.cli import main

    out = make_out(tmp_path / "out", ["2026-10-01"])
    assert main(["upload", "--store", f"file://{tmp_path / 'bucket'}", "--out", str(out)]) == 0
    assert (tmp_path / "bucket" / "manifest.json").is_file()
    assert "uploaded" in capsys.readouterr().out
