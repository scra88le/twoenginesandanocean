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


def _build(args: argparse.Namespace) -> int:
    import xarray as xr

    from .derived import compute_layers
    from .publish import encode_date, publish_date
    from .tidy import build_tidy, write_tidy

    tidy_path = args.work / f"tidy_{args.date.isoformat()}.nc"
    if tidy_path.is_file():
        tidy = xr.load_dataset(tidy_path)
    else:
        try:
            tidy = build_tidy(args.date, args.raw)
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            return 1
        write_tidy(tidy, args.work)
    files, stats = encode_date(compute_layers(tidy))
    publish_date(args.out, args.date.isoformat(), files)
    for lid, st in stats.items():
        if st["clipped"] or st["nodata_pct"]:
            print(f"  {lid}: {st['clipped']} values clipped, {st['nodata_pct']:.2f}% no data")
    size = sum(len(b) for b in files.values())
    print(f"published {args.date} to {args.out}: {len(files)} files, {size / 1e6:.1f} MB")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        return _fetch(args)
    if args.command == "tidy":
        return _tidy(args)
    if args.command == "build":
        return _build(args)
    print(f"{args.command}: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
