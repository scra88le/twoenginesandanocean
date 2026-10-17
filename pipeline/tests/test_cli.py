import pytest

from pipeline.cli import build_parser


def test_build_requires_date_and_out():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["build"])


def test_backfill_defaults_to_90_days():
    args = build_parser().parse_args(["backfill", "--out", "./out"])
    assert args.days == 90
