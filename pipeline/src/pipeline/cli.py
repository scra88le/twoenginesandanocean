"""Command-line entry point: build, backfill, climatology."""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build one date")
    build.add_argument("--date", required=True, help="YYYY-MM-DD")
    build.add_argument("--out", required=True)

    backfill = sub.add_parser("backfill", help="build the last N days")
    backfill.add_argument("--days", type=int, default=90)
    backfill.add_argument("--out", required=True)

    clim = sub.add_parser("climatology", help="one-off 1991-2020 climatology")
    clim.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"{args.command}: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
