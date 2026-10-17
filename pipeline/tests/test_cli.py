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
