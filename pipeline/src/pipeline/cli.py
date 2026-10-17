"""Command-line entry point: build, backfill, climatology."""

import argparse
import sys
import time
from datetime import date
from pathlib import Path


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"not a valid YYYY-MM-DD date: {text!r}") from e


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="download the raw ERA5 archives for one date")
    fetch.add_argument("--date", required=True, type=_date, help="YYYY-MM-DD")
    fetch.add_argument("--raw", type=Path, default=Path("raw"))
    fetch.add_argument("--wait", action="store_true", help="poll until everything is downloaded")

    tidy = sub.add_parser("tidy", help="convert one date's raw archives to a tidy NetCDF")
    tidy.add_argument("--date", required=True, type=_date, help="YYYY-MM-DD")
    tidy.add_argument("--raw", type=Path, default=Path("raw"))
    tidy.add_argument("--work", type=Path, default=Path("work"))

    build = sub.add_parser("build", help="build one date")
    build.add_argument("--date", required=True, help="YYYY-MM-DD")
    build.add_argument("--out", required=True)

    backfill = sub.add_parser("backfill", help="build the last N days")
    backfill.add_argument("--days", type=int, default=90)
    backfill.add_argument("--out", required=True)

    clim = sub.add_parser("climatology", help="one-off 1991-2020 climatology")
    clim.add_argument("--out", required=True)
    return parser


def _fetch(args: argparse.Namespace) -> int:
    from .fetch import client, fetch_date

    c = client()
    delay = 30.0
    while True:
        pending = fetch_date(c, args.date, args.raw)
        if not pending:
            print(f"{args.date}: all archives downloaded to {args.raw}")
            return 0
        print(f"{args.date}: waiting on {', '.join(pending)}")
        if not args.wait:
            return 0
        time.sleep(delay)
        delay = min(delay * 1.5, 300.0)  # exponential backoff, capped at 5 minutes


def _tidy(args: argparse.Namespace) -> int:
    from .tidy import build_tidy, write_tidy

    try:
        ds = build_tidy(args.date, args.raw)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"wrote {write_tidy(ds, args.work)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        return _fetch(args)
    if args.command == "tidy":
        return _tidy(args)
    print(f"{args.command}: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
