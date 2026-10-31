"""The ocean overlay (`pipeline.ocean`): regridding, the Atlantic mask, one day end to end,
encoding, and the run that fetches, builds and publishes, locally and against a store."""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from pipeline import derived as d
from pipeline import ocean, publish
from pipeline.encode import MASKED, NODATA, decode, png_to_ints
from pipeline.layers import OCEAN_LIMBS
from pipeline.store import LocalStore

# A small synthetic GLO12 subset: 1/4 degree, 20-35 N, 85-10 W, five levels.
STEP = 0.25
LAT = np.arange(20.0, 35.0 + STEP / 2, STEP)
LON = np.arange(-85.0, -10.0 + STEP / 2, STEP)
DEPTH = np.array([5.0, 15.0, 30.0, 600.0, 1600.0])  # edges 0, 10, 22.5, 315, 1100, 2100
FLORIDA = -80.5  # land west of this


def synthetic_day(v_upper=0.1, v_deep=-0.1, u=0.0):
    """Northward flow above 1100 m and southward below, Florida as land, and a shallow
    (315 m) shelf east of 20 W where the bottom two levels are dry."""
    nz, ny, nx = DEPTH.size, LAT.size, LON.size
    vv = np.empty((nz, ny, nx))
    vv[:4], vv[4] = v_upper, v_deep
    uu = np.full((nz, ny, nx), u)
    land = np.broadcast_to(LON < FLORIDA, (ny, nx))
    shelf = np.broadcast_to(LON > -20, (ny, nx))
    for a in (uu, vv):
        a[:, land] = np.nan
        a[3:, shelf] = np.nan
    return uu, vv, DEPTH, LAT, LON


# ---- regridding and the basin ---------------------------------------------------------


def test_overlap_gives_glo12_points_half_weight_on_cell_edges():
    lon = -180 + np.arange(13) / 12  # 1/12 degree points from -180 to -179
    w = ocean.overlap(lon, 1 / 12, np.array([-180.0]), np.array([-179.5]))
    assert w[0, :7].tolist() == pytest.approx([0.5, 1, 1, 1, 1, 1, 0.5])
    assert w[0, 7:].sum() == 0


def test_regrid_keeps_constants_and_counts_land_as_no_flow():
    rg = ocean.regridder(LAT, LON)
    j = int(np.argmin(abs(ocean.GRID_LAT - 27.25)))
    col = lambda lon: int(np.argmin(abs(ocean.GRID_LON - lon)))  # noqa: E731
    ones = rg.mean(np.ones((LAT.size, LON.size)))
    inside = np.isfinite(ones)
    assert np.allclose(ones[inside], 1)
    assert not inside[j, col(-90.25)]  # outside the subset
    land_west = np.where(LON[None, :] < -50, np.nan, 1.0) * np.ones((LAT.size, 1))
    got = rg.mean(land_west)
    assert got[j, col(-49.75)] == pytest.approx(1)  # all water
    # [-50.5, -50): only the half of the point at -50 that lies inside it is water.
    assert got[j, col(-50.25)] == pytest.approx(0.25)
    assert got[j, col(-60.25)] == pytest.approx(0)


def test_regrid_preserves_the_area_integral():
    rg = ocean.regridder(LAT, LON)
    x = np.random.default_rng(1).normal(size=(LAT.size, LON.size))
    o_lat = ocean.overlap(LAT, STEP, ocean.GRID_LAT - 0.25, ocean.GRID_LAT + 0.25)
    o_lon = ocean.overlap(LON, STEP, ocean.GRID_LON - 0.25, ocean.GRID_LON + 0.25)
    rows, cols = rg.covered.any(1), rg.covered.any(0)
    assert (rg.covered == np.outer(rows, cols)).all()
    weight = np.outer(np.cos(np.deg2rad(LAT)) * o_lat[rows].sum(0), o_lon[cols].sum(0))
    got = rg.mean(x)
    assert np.nansum(got * rg.norm) == pytest.approx((x * weight).sum())


def _fraction(ocean_where):
    lat, lon = np.meshgrid(ocean.GRID_LAT, ocean.GRID_LON, indexing="ij")
    return ocean_where(lat, lon).astype(float)


def test_basin_is_the_atlantic_connected_to_the_seed():
    # Ocean everywhere except a land bar at 0-5 E, which cuts off a "Mediterranean" east of it.
    frac = _fraction(lambda lat, lon: ~((lon > 0) & (lon < 5)))
    basin = ocean.basin_mask(frac)
    at = lambda lon, lat: basin[  # noqa: E731
        int(np.argmin(abs(ocean.GRID_LAT - lat))), int(np.argmin(abs(ocean.GRID_LON - lon)))
    ]
    assert at(-30, 30) and at(-60, 10) and at(-90, 25)  # Gulf of Mexico
    assert not at(10, 40)  # behind the land bar
    assert not at(-90, 0) and not at(-110, 10)  # Pacific: west of the Central American divide
    assert at(-76, 10)  # the Caribbean coast of Colombia


def test_thin_ocean_cells_are_land():
    frac = _fraction(lambda lat, lon: lon > -1e9) * 0.2
    assert not ocean.basin_mask(frac).any()


# ---- one day --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def day():
    return ocean.reduce_day(*synthetic_day())


def _cell(lon, lat):
    return int(np.argmin(abs(ocean.GRID_LAT - lat))), int(np.argmin(abs(ocean.GRID_LON - lon)))


def test_reduce_day_integrates_each_limb(day):
    uu, vv, h = day.limbs["amoc_upper"]
    j, i = _cell(-50.25, 27.25)
    assert h[j, i] == pytest.approx(1100)
    assert vv[j, i] == pytest.approx(110)
    assert uu[j, i] == pytest.approx(0)
    _, vd, hd = day.limbs["amoc_deep"]
    assert hd[j, i] == pytest.approx(1000) and vd[j, i] == pytest.approx(-100)
    j, i = _cell(-15.25, 27.25)  # the shelf: 315 m of water, none of it deep
    assert h[j, i] == pytest.approx(315) and hd[j, i] == pytest.approx(0)
    j, i = _cell(-82.25, 27.25)  # Florida
    assert h[j, i] == pytest.approx(0) and day.ocean_fraction[j, i] == pytest.approx(0)


def test_reduce_day_diagnoses_the_overturning_at_26_5_n(day):
    s = day.section
    assert s["z_max_m"] == pytest.approx(1100)
    # Water from 81 W (Florida, land up to 80.5 W) to 13 W, at 1/4 degree.
    lon = LON[(LON >= ocean.SECTION_LON[0]) & (LON <= ocean.SECTION_LON[1])]
    deep_cols = lon <= -20
    dx = d.EARTH_RADIUS * np.cos(np.deg2rad(26.5)) * np.deg2rad(STEP)
    wet = lon >= FLORIDA
    upper = (wet & deep_cols).sum() * 110 + (wet & ~deep_cols).sum() * 31.5
    assert s["amoc_upper_sv"] == pytest.approx(upper * dx / d.SVERDRUP)
    assert s["amoc_deep_sv"] == pytest.approx(-(wet & deep_cols).sum() * 100 * dx / d.SVERDRUP)
    assert s["psi_max_sv"] == pytest.approx(s["amoc_upper_sv"])


def test_save_and_load_round_trip(tmp_path, day):
    path = tmp_path / "2026-10-01.npz"
    ocean.save_day(path, day)
    back = ocean.load_saved(path)
    assert back.section == pytest.approx(day.section)
    for lid in OCEAN_LIMBS:
        for a, b in zip(back.limbs[lid], day.limbs[lid], strict=True):
            np.testing.assert_allclose(a, b, rtol=1e-6, equal_nan=True)


def test_window_mean_averages_transport_and_thickness():
    a = ocean.reduce_day(*synthetic_day(v_upper=0.1))
    b = ocean.reduce_day(*synthetic_day(v_upper=0.3))
    m = ocean.window_mean([a, b])
    j, i = _cell(-50.25, 27.25)
    assert m.limbs["amoc_upper"][1][j, i] == pytest.approx(220)
    assert m.days == 2
    assert m.section["amoc_upper_sv"] == pytest.approx(
        (a.section["amoc_upper_sv"] + b.section["amoc_upper_sv"]) / 2
    )


def _decode(files, name, lid):
    spec = OCEAN_LIMBS[lid]
    if name.endswith("_uv.png"):
        cu, cv = png_to_ints(files[name])
        return [decode(c, *spec.uv_encode, step=spec.uv_resolution) for c in (cu, cv)], (cu, cv)
    codes = png_to_ints(files[name])
    return decode(codes, *spec.encode, log=True, step=spec.resolution), codes


def test_encode_ocean_writes_transport_and_velocity(day):
    files = ocean.encode_ocean(day, None)
    assert set(files) == {f"{lid}{s}.png" for lid in OCEAN_LIMBS for s in ("", "_uv")}
    j, i = _cell(-50.25, 27.25)
    mag, codes = _decode(files, "amoc_upper.png", "amoc_upper")
    assert mag[j, i] == pytest.approx(110, rel=0.005)
    (ub, vb), _ = _decode(files, "amoc_upper_uv.png", "amoc_upper")
    assert vb[j, i] == pytest.approx(0.1, abs=0.001) and ub[j, i] == pytest.approx(0, abs=0.001)
    (_, vd), (cu, _) = _decode(files, "amoc_deep_uv.png", "amoc_deep")
    assert vd[j, i] == pytest.approx(-0.1, abs=0.0005)
    assert codes[_cell(-82.25, 27.25)] == MASKED  # Florida
    assert codes[_cell(-120.25, 27.25)] == NODATA  # outside the subset
    assert cu[_cell(-15.25, 27.25)] == MASKED  # the shelf has no deep water


def test_encode_ocean_adds_the_mean_files(day):
    files = ocean.encode_ocean(day, day)
    assert "amoc_deep_30d_uv.png" in files and "amoc_upper_30d.png" in files


# ---- fetching -------------------------------------------------------------------------


def test_fetch_day_asks_for_the_whole_utc_day_over_the_box(tmp_path):
    calls = []

    def subset(**kw):
        calls.append(kw)
        (Path(kw["output_directory"]) / kw["output_filename"]).write_bytes(b"nc")

    path = ocean.fetch_day(date(2026, 10, 1), tmp_path, subset=subset)
    assert path == tmp_path / "glo12_2026-10-01.nc" and path.is_file()
    kw = calls[0]
    assert kw["dataset_id"] == ocean.DATASET_ID and kw["variables"] == ["uo", "vo"]
    assert (kw["start_datetime"], kw["end_datetime"]) == (
        "2026-10-01T00:00:00", "2026-10-01T23:59:59",
    )  # fmt: skip
    assert kw["minimum_longitude"] == ocean.BOX.west and kw["maximum_latitude"] == ocean.BOX.north
    assert kw["overwrite"] is True


def test_load_day_reads_a_glo12_subset(tmp_path):
    xr = pytest.importorskip("xarray")
    uu, vv, depth, lat, lon = synthetic_day()
    ds = xr.Dataset(
        {
            "uo": (("time", "depth", "latitude", "longitude"), uu[None].astype("float32")),
            "vo": (("time", "depth", "latitude", "longitude"), vv[None].astype("float32")),
        },
        coords={"time": [np.datetime64("2026-10-01")], "depth": depth, "latitude": lat,
                "longitude": lon},
    )  # fmt: skip
    path = tmp_path / "glo12.nc"
    ds.to_netcdf(path)
    u, v, dep, la, lo = ocean.load_day(path)
    assert u.shape == (5, LAT.size, LON.size)
    day = ocean.reduce_day(u, v, dep, la, lo)
    assert day.section["z_max_m"] == pytest.approx(1100)


# ---- the run --------------------------------------------------------------------------

LATEST = date(2026, 10, 18)


def _out(tmp_path, dates):
    out = tmp_path / "out"
    out.mkdir()
    built_at = "2026-10-20T00:00:00Z"
    manifest = publish.build_manifest([x.isoformat() for x in dates], built_at, ["carnot"])
    (out / "manifest.json").write_text(json.dumps(manifest))
    return out


class Fake:
    """A Copernicus Marine stand-in: records the days fetched, fails on some."""

    def __init__(self, fail=()):
        self.days: list[date] = []
        self.fail = set(fail)

    def fetch(self, day, dest):
        if day in self.fail:
            raise ConnectionError("service unavailable")
        self.days.append(day)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"glo12_{day}.nc"
        path.write_text(day.isoformat())
        return path

    @staticmethod
    def load(path):
        k = date.fromisoformat(Path(path).read_text()).day
        return synthetic_day(v_upper=0.1 + 0.001 * k)


def test_run_fetches_the_dates_first_then_their_windows_within_the_budget(tmp_path):
    dates = [LATEST - timedelta(days=k) for k in range(2, -1, -1)]
    out = _out(tmp_path, dates)
    fake = Fake()
    result = ocean.run_ocean(out, tmp_path / "work", max_fetch=5, fetch=fake.fetch, load=fake.load)
    assert fake.days == [LATEST, LATEST - timedelta(1), LATEST - timedelta(2),
                         LATEST - timedelta(3), LATEST - timedelta(4)]  # fmt: skip
    assert result.built == [x.isoformat() for x in sorted(dates, reverse=True)]
    m = json.loads((out / "manifest.json").read_text())
    entry = m["ocean"]["dates"][LATEST.isoformat()]
    assert entry["window_days"] == 5 and entry["mean"] is None  # too few days for a mean
    assert entry["daily"]["z_max_m"] == pytest.approx(1100)
    assert (out / "ocean" / LATEST.isoformat() / "amoc_upper_uv.png").is_file()
    assert not (out / "ocean" / LATEST.isoformat() / "amoc_upper_30d.png").exists()
    assert not list((tmp_path / "work" / "ocean" / "raw").glob("*.nc"))  # downloads deleted
    assert m["ocean"]["limbs"]["amoc_deep"]["bottom_m"] is None
    assert m["built_layers"] == ["carnot"] and m["dates"] == [x.isoformat() for x in dates]


def test_the_mean_appears_once_the_window_fills_and_dates_are_rebuilt_only_then(tmp_path):
    out = _out(tmp_path, [LATEST])
    fake = Fake()
    work = tmp_path / "work"
    ocean.run_ocean(out, work, max_fetch=20, fetch=fake.fetch, load=fake.load)
    m = json.loads((out / "manifest.json").read_text())
    assert m["ocean"]["dates"][LATEST.isoformat()]["mean"] is None
    r = ocean.run_ocean(out, work, max_fetch=20, fetch=fake.fetch, load=fake.load)
    assert len(fake.days) == 30 and r.built == [LATEST.isoformat()]
    m = json.loads((out / "manifest.json").read_text())
    entry = m["ocean"]["dates"][LATEST.isoformat()]
    assert entry["window_days"] == 30 and entry["mean"] is not None
    assert (out / "ocean" / LATEST.isoformat() / "amoc_deep_30d_uv.png").is_file()
    r = ocean.run_ocean(out, work, max_fetch=20, fetch=fake.fetch, load=fake.load)
    assert r.fetched == [] and r.built == []  # complete: nothing to do


def test_a_failed_fetch_is_logged_and_the_others_still_build(tmp_path):
    dates = [LATEST - timedelta(days=1), LATEST]
    out = _out(tmp_path, dates)
    fake = Fake(fail={LATEST})
    r = ocean.run_ocean(out, tmp_path / "work", max_fetch=2, fetch=fake.fetch, load=fake.load)
    assert LATEST in r.failed and r.built == [(LATEST - timedelta(1)).isoformat()]
    m = json.loads((out / "manifest.json").read_text())
    assert list(m["ocean"]["dates"]) == [(LATEST - timedelta(1)).isoformat()]


def test_dates_that_leave_the_window_leave_the_ocean_block_and_the_state(tmp_path):
    old, new = LATEST - timedelta(days=100), LATEST
    out = _out(tmp_path, [old])
    fake = Fake()
    work = tmp_path / "work"
    ocean.run_ocean(out, work, max_fetch=1, fetch=fake.fetch, load=fake.load)
    assert (work / "ocean" / f"{old}.npz").is_file()
    # The ERA5 job publishes a new date and drops the old one.
    publish.publish_date(out, new.isoformat(), {}, keep_days=1)
    m = json.loads((out / "manifest.json").read_text())
    assert m["ocean"]["dates"] == {} and not (out / "ocean" / old.isoformat()).exists()
    ocean.run_ocean(out, work, max_fetch=1, fetch=fake.fetch, load=fake.load)
    assert not (work / "ocean" / f"{old}.npz").exists()
    m = json.loads((out / "manifest.json").read_text())
    assert list(m["ocean"]["dates"]) == [new.isoformat()]


def test_era5_manifest_writes_carry_the_ocean_block(tmp_path):
    out = _out(tmp_path, [LATEST])
    fake = Fake()
    ocean.run_ocean(out, tmp_path / "work", max_fetch=1, fetch=fake.fetch, load=fake.load)
    block = json.loads((out / "manifest.json").read_text())["ocean"]
    publish.refresh_manifest(out)
    assert json.loads((out / "manifest.json").read_text())["ocean"] == block
    publish.publish_date(out, (LATEST - timedelta(1)).isoformat(), {})
    assert json.loads((out / "manifest.json").read_text())["ocean"] == block


def test_daily_step_round_trips_its_state_through_the_store(tmp_path):
    store = LocalStore(tmp_path / "bucket")
    seed = _out(tmp_path, [LATEST])
    store.put("manifest.json", seed / "manifest.json")
    fake = Fake()
    run = lambda out, work: ocean.run_ocean_daily(  # noqa: E731
        store, out, work, max_fetch=2, fetch=fake.fetch, load=fake.load, check=lambda: True
    )
    r = run(tmp_path / "run1", tmp_path / "w1")
    assert r.built == [LATEST.isoformat()]
    keys = store.list("")
    assert f"state/ocean/{LATEST}.npz" in keys and f"ocean/{LATEST}/amoc_upper.png" in keys
    assert "ocean" in json.loads((tmp_path / "bucket" / "manifest.json").read_text())
    r = run(tmp_path / "run2", tmp_path / "w2")  # a fresh runner: state comes from the store
    assert fake.days[:2] == [LATEST, LATEST - timedelta(1)]
    assert fake.days[2:] == [LATEST - timedelta(2), LATEST - timedelta(3)]  # not re-fetched
    entry = json.loads((tmp_path / "bucket" / "manifest.json").read_text())["ocean"]["dates"]
    assert entry[LATEST.isoformat()]["window_days"] == 4


def test_bad_credentials_change_nothing(tmp_path):
    store = LocalStore(tmp_path / "bucket")
    seed = _out(tmp_path, [LATEST])
    store.put("manifest.json", seed / "manifest.json")
    before = store.list("")
    with pytest.raises(RuntimeError, match="credentials"):
        ocean.run_ocean_daily(store, tmp_path / "o", tmp_path / "w", check=lambda: False)
    assert store.list("") == before
