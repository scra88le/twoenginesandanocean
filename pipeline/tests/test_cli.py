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
