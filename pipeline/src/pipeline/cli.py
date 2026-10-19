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

    rebuild = sub.add_parser("rebuild", help="rebuild every published date from tidy files")
    rebuild.add_argument("--out", type=Path, required=True)
    rebuild.add_argument("--raw", type=Path, default=Path("raw"))
    rebuild.add_argument("--work", type=Path, default=Path("work"))

    series = sub.add_parser("series", help="rebuild the 90-day series chunks")
    series.add_argument("--out", type=Path, required=True)

    clim = sub.add_parser("climatology", help="fetch and publish the 1991-2020 climatology")
    clim.add_argument("--out", type=Path, required=True)
    clim.add_argument("--raw", type=Path, default=Path("raw"))
    clim.add_argument("--work", type=Path, default=Path("work"))
    clim.add_argument("--wait", action="store_true", help="keep going until it is published")

    backfill = sub.add_parser("backfill", help="fetch and build the last N available days")
    backfill.add_argument("--days", type=int, default=90)
    backfill.add_argument("--out", type=Path, required=True)
    backfill.add_argument("--raw", type=Path, default=Path("raw"))
    backfill.add_argument("--work", type=Path, default=Path("work"))
    backfill.add_argument("--wait", action="store_true", help="keep going until nothing is pending")
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
    from .points import build_series

    print(f"published {args.date} to {args.out}; series: rebuilt {build_series(args.out)} files")
    return 0


def _climatology(args: argparse.Namespace) -> int:
    from .climatology import build_climatology, chunks_done, fetch_chunks
    from .fetch import client
    from .publish import refresh_manifest

    c = None
    delay = 60.0
    while not chunks_done(args.work):
        c = c or client()
        pending = fetch_chunks(c, args.raw, args.work)
        if chunks_done(args.work):
            break
        print(
            f"waiting on {len(pending)} climatology request(s); next check in {delay:.0f} s",
            flush=True,
        )
        if not args.wait:
            return 0
        time.sleep(delay)
        delay = min(delay * 1.5, 300.0)
    print(f"climatology: wrote {build_climatology(args.work, args.out)} files", flush=True)
    refresh_manifest(args.out)
    print("manifest refreshed; run `rebuild` to add anomalies to the published dates")
    return 0


def _rebuild(args: argparse.Namespace) -> int:
    from .run import rebuild

    failed = rebuild(args.raw, args.work, args.out, log=lambda msg: print(msg, flush=True))
    return 1 if failed else 0


def _series(args: argparse.Namespace) -> int:
    from .points import build_series

    print(f"series: rebuilt {build_series(args.out)} files")
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
    if args.command == "rebuild":
        return _rebuild(args)
    if args.command == "series":
        return _series(args)
    if args.command == "climatology":
        return _climatology(args)
    print(f"{args.command}: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
