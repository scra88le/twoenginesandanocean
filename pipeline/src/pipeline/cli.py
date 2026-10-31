"""Command-line entry point: fetch, build, backfill, climatology, daily, ocean, upload."""

import argparse
import os
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

    store_default = os.environ.get("STORE_URL")
    daily = sub.add_parser(
        "daily", help="collect and submit CDS requests, build new dates and publish them to a store"
    )
    daily.add_argument("--store", default=store_default, help="file:///dir or s3://bucket[/prefix]")
    daily.add_argument("--days", type=int, default=10, help="how many recent dates to attempt")
    daily.add_argument("--out", type=Path, default=Path("out"))
    daily.add_argument("--raw", type=Path, default=Path("raw"))
    daily.add_argument("--work", type=Path, default=Path("work"))

    ocean = sub.add_parser(
        "ocean",
        help="build the AMOC overlay (Copernicus Marine GLO12) for the published dates",
    )
    ocean.add_argument(
        "--store",
        default=None,
        help="the daily job: state from and publish to this store (file:///dir or "
        "s3://bucket[/prefix]); without it ./out is updated in place",
    )
    ocean.add_argument(
        "--max-fetch", type=int, default=None, help="days to download in this run (default 15)"
    )
    ocean.add_argument("--out", type=Path, default=Path("out"))
    ocean.add_argument("--work", type=Path, default=Path("work"))

    upload = sub.add_parser("upload", help="publish a local data root to a store")
    upload.add_argument(
        "--store", default=store_default, help="file:///dir or s3://bucket[/prefix]"
    )
    upload.add_argument("--out", type=Path, required=True)

    clim = sub.add_parser("climatology", help="fetch and publish the 1991-2020 climatology")
    clim.add_argument("--out", type=Path, required=True)
    clim.add_argument("--raw", type=Path, default=Path("raw"))
    clim.add_argument("--work", type=Path, default=Path("work"))
    clim.add_argument("--wait", action="store_true", help="keep going until it is published")
    clim.add_argument(
        "--partial",
        action="store_true",
        help="don't wait for every request: publish from the parts that have arrived "
        "(still queues what is missing)",
    )

    lw = sub.add_parser("fetch-str", help="add surface net longwave (lw_up) to tidy files")
    lw.add_argument("--raw", type=Path, default=Path("raw"))
    lw.add_argument("--work", type=Path, default=Path("work"))
    lw.add_argument("--wait", action="store_true", help="keep going until every date has it")

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


def _need_store(args: argparse.Namespace) -> str | None:
    if not args.store:
        print(
            "no store: pass --store or set STORE_URL (file:///dir or s3://bucket[/prefix])",
            file=sys.stderr,
        )
    return args.store


def _daily(args: argparse.Namespace) -> int:
    from .daily import run_daily
    from .fetch import client
    from .store import open_store

    if not _need_store(args):
        return 2
    result = run_daily(
        open_store(args.store), client(), args.raw, args.work, args.out, days=args.days,
        log=lambda msg: print(msg, flush=True),
    )  # fmt: skip
    print(
        f"built {len(result.built)}, failed {len(result.failed)}, "
        f"{len(result.pending)} CDS request(s) still pending"
    )
    for day, problems in result.failed.items():
        print(f"::error::{day} not published: {'; '.join(problems)}", file=sys.stderr)
    return 1 if result.failed else 0


def _ocean(args: argparse.Namespace) -> int:
    from . import ocean
    from .store import open_store

    log = lambda msg: print(msg, flush=True)  # noqa: E731
    n = args.max_fetch if args.max_fetch is not None else ocean.MAX_FETCH
    if args.store:
        result = ocean.run_ocean_daily(open_store(args.store), args.out, args.work, n, log=log)
    else:
        result = ocean.run_ocean(args.out, args.work, n, log=log)
    print(f"ocean: fetched {len(result.fetched)} days, built {len(result.built)} dates")
    for day, problem in result.failed.items():
        print(f"::error::ocean {day} not fetched: {problem}", file=sys.stderr)
    return 1 if result.failed else 0


def _upload(args: argparse.Namespace) -> int:
    from .deploy import upload
    from .store import open_store

    if not _need_store(args):
        return 2
    result = upload(open_store(args.store), args.out, log=lambda msg: print(msg, flush=True))
    print(f"{result.uploaded} uploaded, {result.skipped} unchanged, {result.deleted} deleted")
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
        if chunks_done(args.work) or args.partial:
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


def _fetch_str(args: argparse.Namespace) -> int:
    from .fetch import client
    from .lw_backfill import backfill_lw_up

    updated, left = backfill_lw_up(
        client(), args.work, args.raw, wait=args.wait, log=lambda msg: print(msg, flush=True)
    )
    print(f"lw_up added to {updated} tidy file(s); {left} still without")
    return 0 if left == 0 else 1


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
    if args.command == "fetch-str":
        return _fetch_str(args)
    if args.command == "rebuild":
        return _rebuild(args)
    if args.command == "series":
        return _series(args)
    if args.command == "daily":
        return _daily(args)
    if args.command == "upload":
        return _upload(args)
    if args.command == "ocean":
        return _ocean(args)
    if args.command == "climatology":
        return _climatology(args)
    print(f"{args.command}: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
