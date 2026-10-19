import csv
import json
from datetime import date, timedelta

from _helpers import synthetic_tidy

from pipeline import run

D = date(2026, 10, 1)


def write_tidy(work, day, **overrides):
    work.mkdir(parents=True, exist_ok=True)
    ds = synthetic_tidy(tsr=240.0, **overrides)
    ds.attrs["date"] = day.isoformat()
    ds.to_netcdf(work / f"tidy_{day}.nc")


def test_build_date_publishes_a_valid_day(tmp_path):
    write_tidy(tmp_path / "work", D)
    problems = run.build_date(D, tmp_path / "raw", tmp_path / "work", tmp_path / "out")
    assert problems == []
    assert json.loads((tmp_path / "out" / "manifest.json").read_text())["dates"] == ["2026-10-01"]
    row = next(csv.DictReader((tmp_path / "out" / "logs" / "global_means.csv").open()))
    assert row["status"] == "ok"


def test_build_date_does_not_publish_a_failed_day(tmp_path):
    write_tidy(tmp_path / "work", D, tp=9 / 86_400)  # 9 mm/day global mean: implausible
    problems = run.build_date(D, tmp_path / "raw", tmp_path / "work", tmp_path / "out")
    assert problems and "tp" in problems[0]
    assert not (tmp_path / "out" / "manifest.json").exists()
    assert not (tmp_path / "out" / "fields" / "2026-10-01").exists()
    row = next(csv.DictReader((tmp_path / "out" / "logs" / "global_means.csv").open()))
    assert row["status"] == "failed"


def test_target_dates_are_the_last_n_days_up_to_the_latest():
    got = run.target_dates(date(2026, 10, 12), 90)
    assert len(got) == 90 and got[-1] == date(2026, 10, 12) and got[0] == date(2026, 7, 15)


def test_backfill_builds_ready_dates_and_skips_published_ones(tmp_path):
    days = run.target_dates(D, 3)  # Sep 29, 30, Oct 1
    out, raw, work = tmp_path / "out", tmp_path / "raw", tmp_path / "work"
    for d in days[:2]:
        write_tidy(work, d)
    run.build_date(days[0], raw, work, out)  # already published
    for d in days[:2]:  # raw archives present for the first two only
        raw.mkdir(exist_ok=True)
        for name in ("single_mean", "single_sum", "pressure_mean"):
            (raw / f"{name}_{d}.nc").write_bytes(b"x")
    asked, built = [], []

    def fake_fetch(c, wanted, raw_dir):
        asked.append(list(wanted))
        return ["single_mean_2026-10-01_2026-10-01.nc"]

    def fake_build(day, raw_dir, work_dir, out_dir):
        built.append(day)
        return run.build_date(day, raw_dir, work_dir, out_dir)

    result = run.backfill(None, D, 3, raw, work, out, fetch=fake_fetch, build=fake_build)
    assert asked == [days[1:]]  # the published day isn't fetched again
    assert built == [days[1]]  # only the day whose archives are all there
    assert result.pending == ["single_mean_2026-10-01_2026-10-01.nc"]
    assert result.built == [days[1]] and result.failed == {}
    assert json.loads((out / "manifest.json").read_text())["dates"] == [str(d) for d in days[:2]]


def test_backfill_rebuilds_series_only_after_a_pass_that_published(tmp_path):
    out, raw, work = tmp_path / "out", tmp_path / "raw", tmp_path / "work"
    days = run.target_dates(D, 2)
    write_tidy(work, days[0])
    rebuilt = []
    passes = iter([["pending"], []])  # one pass waiting on CDS, then done

    def fake_fetch(c, wanted, raw_dir):
        return next(passes)

    def series(out_dir):
        rebuilt.append(out_dir)
        return 0

    run.backfill(
        None, D, 2, raw, work, out, wait=True, fetch=fake_fetch, series=series,
        sleep=lambda s: None,
    )  # fmt: skip
    assert rebuilt == [out]  # the first pass published days[0]; the second published nothing
    assert (out / "points" / str(days[0])).is_dir()


def test_rebuild_reruns_published_dates_and_the_series(tmp_path):
    out, raw, work = tmp_path / "out", tmp_path / "raw", tmp_path / "work"
    days = run.target_dates(D, 2)
    for d in days:
        write_tidy(work, d)
        run.build_date(d, raw, work, out)
    (work / f"tidy_{days[0]}.nc").unlink()  # this one can't be rebuilt
    logs = []
    assert run.rebuild(raw, work, out, log=logs.append) == {}
    assert logs[0] == f"{days[0]}: no tidy file, skipped"
    assert logs[1] == f"{days[1]}: rebuilt"
    assert (out / "series" / "olr" / "0_0.bin").is_file()


def test_old_raw_archives_and_tidy_files_are_pruned(tmp_path):
    raw, work = tmp_path / "raw", tmp_path / "work"
    raw.mkdir()
    work.mkdir()
    newest = date(2026, 10, 12)
    for k in (0, 29, 30, 31):
        d = newest - timedelta(days=k)
        (raw / f"single_mean_{d}.nc").write_bytes(b"x")
        (work / f"tidy_{d}.nc").write_bytes(b"x")  # built, so its raw archives may go
    for k in (0, 89, 90):
        (work / f"tidy_{newest - timedelta(days=k)}.nc").write_bytes(b"x")
    (raw / "pending.json").write_text("{}")
    run.prune(raw, work, newest, raw_days=30, tidy_days=90)
    assert sorted(p.name for p in raw.iterdir()) == sorted(
        ["pending.json"] + [f"single_mean_{newest - timedelta(days=k)}.nc" for k in (0, 29)]
    )
    assert sorted(p.name for p in work.iterdir()) == sorted(
        f"tidy_{newest - timedelta(days=k)}.nc" for k in (0, 29, 30, 31, 89)
    )


def test_raw_archives_of_dates_not_yet_built_are_kept(tmp_path):
    # A July date whose sums are still queued must keep its means, or they'd be fetched again.
    raw, work = tmp_path / "raw", tmp_path / "work"
    raw.mkdir()
    work.mkdir()
    newest = date(2026, 10, 12)
    old = newest - timedelta(days=60)
    (raw / f"single_mean_{old}.nc").write_bytes(b"x")
    run.prune(raw, work, newest)
    assert (raw / f"single_mean_{old}.nc").exists()
    (work / f"tidy_{old}.nc").write_bytes(b"x")  # now built
    run.prune(raw, work, newest)
    assert not (raw / f"single_mean_{old}.nc").exists()
