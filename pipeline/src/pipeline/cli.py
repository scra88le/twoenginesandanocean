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

    build = sub.add_parser("build", help="derive, encode and publish one date")
    build.add_argument("--date", required=True, type=_date, help="YYYY-MM-DD")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--raw", type=Path, default=Path("raw"))
    build.add_argument("--work", type=Path, default=Path("work"))

    backfill = sub.add_parser("backfill", help="fetch and build the last N available days")
    backfill.add_argument("--days", type=int, default=90)
    backfill.add_argument("--out", type=Path, required=True)
    backfill.add_argument("--raw", type=Path, default=Path("raw"))
    backfill.add_argument("--work", type=Path, default=Path("work"))
    backfill.add_argument("--wait", action="store_true", help="keep going until nothing is pending")

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


def _build(args: argparse.Namespace) -> int:
    from .run import build_date

    try:
        problems = build_date(args.date, args.raw, args.work, args.out)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    if problems:
        print(f"{args.date}: not published: {'; '.join(problems)}", file=sys.stderr)
        return 1
    print(f"published {args.date} to {args.out}")
    return 0


def _backfill(args: argparse.Namespace) -> int:
    from .fetch import client
    from .run import backfill, latest_available

    c = client()
    latest = latest_available(c)
    print(f"latest ERA5 daily date: {latest}; making sure the last {args.days} days are built")
    result = backfill(
        c, latest, args.days, args.raw, args.work, args.out, wait=args.wait,
        log=lambda msg: print(msg, flush=True),
    )  # fmt: skip
    print(
        f"built {len(result.built)}, failed {len(result.failed)}, "
        f"{len(result.pending)} CDS request(s) still pending"
    )
    return 1 if result.failed else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        return _fetch(args)
    if args.command == "tidy":
        return _tidy(args)
    if args.command == "build":
        return _build(args)
    if args.command == "backfill":
        return _backfill(args)
    print(f"{args.command}: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
