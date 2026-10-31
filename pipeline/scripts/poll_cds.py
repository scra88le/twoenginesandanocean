"""Poll the CDS until the milestone 14 downloads are in, using no Claude tokens.

    python pipeline/scripts/poll_cds.py [--every 1800] [--once] [--status]

Each round it advances both download jobs one step without waiting:

- the `str` backfill (`lw_backfill.backfill_lw_up`): collects finished months, merges them into
  the tidy files as `lw_up`, queues the next months;
- the second climatology request set (`climatology.fetch_chunks`): collects finished chunks,
  reduces them to monthly sums in `work/clim/`, queues the next ones.

It stops when every tidy file has `lw_up` and every climatology part has arrived. It does not
build the climatology, rebuild the dates or upload anything: that is a decision for a person.
Run it in tmux or under nohup, from the repo root, with the venv's Python:

    nohup .venv/bin/python pipeline/scripts/poll_cds.py > /tmp/poll_cds.log 2>&1 &

Rejected requests (the CDS limits what is queued) are resubmitted once per round, so a long
`--every` keeps that churn low. Network errors are logged and retried; ten rounds in a row
that fail stop it with exit status 1. Only one copy runs at a time (`raw/poll_cds.lock`).
"""

from __future__ import annotations

import argparse
import fcntl
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

MAX_FAILURES = 10


def log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def status(work: Path) -> tuple[int, list[str], bool]:
    """(dates still without lw_up, climatology parts not yet in, everything done)."""
    from pipeline.climatology import PARTS, chunks_done
    from pipeline.lw_backfill import dates_needing_lw_up

    left = len(dates_needing_lw_up(work))
    missing = [p.name for p in PARTS if not chunks_done(work, (p,))]
    return left, missing, left == 0 and not missing


def one_round(raw: Path, work: Path) -> None:
    from pipeline.climatology import fetch_chunks
    from pipeline.fetch import client
    from pipeline.lw_backfill import backfill_lw_up

    c = client()
    pending = fetch_chunks(c, raw, work)
    log(f"climatology: {len(pending)} request(s) pending")
    updated, left = backfill_lw_up(c, work, raw, wait=False, log=log)
    log(f"str: {updated} date(s) updated, {left} still without lw_up")


def another_poller_running() -> bool:
    """A `fetch-str --wait` left running would race this script on the request state."""
    out = subprocess.run(
        ["pgrep", "-af", "pipeline.cli fetch-str"], capture_output=True, text=True
    ).stdout
    return any("pgrep" not in line for line in out.splitlines())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", type=Path, default=Path("raw"))
    ap.add_argument("--work", type=Path, default=Path("work"))
    ap.add_argument("--every", type=float, default=1800.0, help="seconds between rounds")
    ap.add_argument("--once", action="store_true", help="one round, then exit")
    ap.add_argument("--status", action="store_true", help="print what is missing; no CDS calls")
    args = ap.parse_args()

    if args.status:
        left, missing, done = status(args.work)
        print(f"dates without lw_up: {left}; climatology parts not in: {missing or 'none'}")
        return 0 if done else 3

    args.raw.mkdir(parents=True, exist_ok=True)
    lock = open(args.raw / "poll_cds.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another poll_cds.py is already running")
        return 2
    if another_poller_running():
        log("a `pipeline.cli fetch-str` process is running; stop it first (it shares the state)")
        return 2

    failures = 0
    while True:
        try:
            one_round(args.raw, args.work)
            failures = 0
        except Exception as exc:  # network or CDS trouble: try again next round
            failures += 1
            log(f"round failed ({failures}/{MAX_FAILURES}): {type(exc).__name__}: {exc}")
            if failures >= MAX_FAILURES:
                return 1
        left, missing, done = status(args.work)
        log(f"{left} date(s) without lw_up; climatology parts not in: {missing or 'none'}")
        if done:
            log(
                "all downloads are in. Next: `python -m pipeline.cli climatology --out out` "
                "(builds net_sfc and the winds), then `rebuild`. Nothing was uploaded."
            )
            return 0
        if args.once:
            return 3
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
