"""Milestone 25: the human layers through the year, on the map, in the build and the store."""

import json
from datetime import date

import numpy as np
import pytest
import xarray as xr
from _helpers import synthetic_tidy
from test_human import GEO, _edgar_file, _energy, _proxies

from pipeline import derived as d
from pipeline import human as h
from pipeline import points as pts
from pipeline.encode import MASKED, NODATA, png_to_ints, quantise, scalar_png
from pipeline.layers import EXTRAS, HUMAN, LAYERS

AREA = d.cell_areas()
EARTH = AREA.sum()
DAYS = np.asarray(d.DAYS_IN_MONTH)


# ---- helpers ---------------------------------------------------------------------------


def write_static(work, world_tw=18.0, bldg_share=0.2, t_normal=None, year=2024):
    """A static file whose P is spread evenly: `world_tw` in every month."""
    p = world_tw * 1e12 / EARTH
    shape = (12, d.NLAT, d.NLON)
    frames = {
        "p_base": np.full(shape, p * (1 - bldg_share)),
        "p_bldg": np.full(shape, p * bldg_share),
        "w_base": np.full(shape, 0.2 * p * (1 - bldg_share)),
        "w_bldg": np.full(shape, 0.3 * p * bldg_share),
    }
    ds = xr.Dataset(
        {k: (("month", "lat", "lon"), v.astype("float32")) for k, v in frames.items()},
        attrs={"year": year, "factor_years": "2016,2017"},
    )
    (work / "human").mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(work / "human" / f"human_{year}.nc")
    if t_normal is not None:
        h.write_t_normal(np.full(shape, t_normal), work)
    return frames


def codes_of(lid, values):
    s = LAYERS[lid] if lid in LAYERS else EXTRAS[lid]
    c, _ = quantise(
        np.full((d.NLAT, d.NLON), values, dtype="float64") if np.isscalar(values) else values,
        np.zeros((d.NLAT, d.NLON), bool), *s.encode, log=getattr(s, "log", False),
        step=s.resolution,
    )  # fmt: skip
    return c


def legacy_tiles(folder, fields):
    """Point chunks in the layout published before milestone 25."""
    folder.mkdir(parents=True, exist_ok=True)
    n = len(pts.LEGACY_POINT_FIELDS) * pts.TILE * pts.TILE * 2
    for name, data in pts.point_tiles(fields).items():
        (folder / name).write_bytes(data[:n])


# ---- point chunks ----------------------------------------------------------------------


def test_tile_layouts_are_told_apart_by_length():
    tile = next(iter(pts.point_tiles({}).values()))
    assert pts.tile_fields(tile) == pts.POINT_FIELDS
    legacy = tile[: len(pts.LEGACY_POINT_FIELDS) * 800]
    assert pts.tile_fields(legacy) == pts.LEGACY_POINT_FIELDS
    with pytest.raises(ValueError):
        pts.tile_fields(tile[:801])


def test_upgrading_a_legacy_tile_keeps_its_fields_and_adds_the_new_ones(tmp_path):
    folder = tmp_path / "p"
    legacy_tiles(folder, {"olr": codes_of("olr", 240.0), "t_skin": codes_of("t_skin", 280.0)})
    work = codes_of("human_work", 0.5)
    q = codes_of("human_q", 2.0)
    assert pts.patch_point_fields(folder, {"human_work": work, "human_q": q}) == 648
    for name in ("0_0.bin", "17_9.bin"):
        tile = pts.read_tile((folder / name).read_bytes())
        assert set(tile) == set(pts.POINT_FIELDS)  # upgraded to the current layout
        assert np.all(tile["olr"] == codes_of("olr", 240.0)[0, 0])
        assert np.all(tile["human_work"] == work[0, 0]) and np.all(tile["human_q"] == q[0, 0])
        assert np.all(tile["human_heat"] == NODATA)
    np.testing.assert_array_equal(pts.read_point_field(folder, "t_skin"), codes_of("t_skin", 280.0))


def test_reading_a_field_an_old_tile_lacks_gives_no_data(tmp_path):
    legacy_tiles(tmp_path / "p", {})
    assert np.all(pts.read_point_field(tmp_path / "p", "human_heat") == NODATA)


# ---- EDGAR's months --------------------------------------------------------------------


def test_edgar_months_from_a_time_axis_and_from_file_names(tmp_path):
    _edgar_file(tmp_path / "a/EDGAR_2024_GHG_CO2_2023_bkl_BUILDINGS_emi.nc", 1.0, "Tonnes")
    months = h._edgar_months(tmp_path / "a/EDGAR_2024_GHG_CO2_2023_bkl_BUILDINGS_emi.nc")
    assert sorted(months) == list(range(1, 13))
    np.testing.assert_allclose(months[3], 25.0)  # 25 sub-cells of 1 t
    _edgar_file(tmp_path / "b/EDGAR_2024_GHG_CO2_2023_7_bkl_BUILDINGS_emi.nc", 2.0, "Tonnes", 1)
    assert list(h._edgar_months(tmp_path / "b/EDGAR_2024_GHG_CO2_2023_7_bkl_BUILDINGS_emi.nc")) == [
        7
    ]
    _edgar_file(tmp_path / "c/EDGAR_2024_GHG_CO2_2023_bkl_BUILDINGS_emi.nc", 2.0, "Tonnes", 1)
    assert list(h._edgar_months(tmp_path / "c/EDGAR_2024_GHG_CO2_2023_bkl_BUILDINGS_emi.nc")) == [0]


def test_load_edgar_monthly_sums_complete_years_of_the_factor_years(tmp_path):
    e = tmp_path / "e"
    for y in (2018, 2019, 2010):
        _edgar_file(e / f"EDGAR_2024_GHG_CO2_{y}_bkl_BUILDINGS_emi.nc", 1.0, "Tonnes")
    for m in range(1, 7):  # 2022: only six months, so left out
        _edgar_file(e / f"EDGAR_2024_GHG_CO2_2022_{m}_bkl_POWER_INDUSTRY_emi.nc", 1.0, "Tonnes", 1)
    monthly, used = h.load_edgar_monthly(e)
    assert used == [2018, 2019]  # 2010 isn't a factor year
    assert set(monthly) == {"buildings"} and monthly["buildings"].shape == (12, 360, 720)
    np.testing.assert_allclose(monthly["buildings"], 2 * 25.0)


# ---- the monthly frames ----------------------------------------------------------------


@pytest.fixture(scope="module")
def grid():
    return h.country_grid(GEO)


def _monthly(winter=3.0):
    """Buildings emissions three times higher in Jan, Feb and Dec; the rest flat."""
    out = {}
    for k, v in _proxies().items():
        if k in d.SECTORS:
            m = np.repeat(v[None], 12, axis=0).astype("float64")
            if k == "buildings":
                m[[0, 1, 11]] *= winter
            out[k] = m
    return out


def _year(frame):
    return (frame * DAYS[:, None, None]).sum(axis=0) / DAYS.sum()


def test_the_year_of_the_monthly_frames_is_the_annual_grid(grid):
    a = h.allocate(_energy(), grid, _proxies(), _monthly())
    p, work, _ = d.cascade(a.components)
    np.testing.assert_allclose(
        _year(a.frames["p_base"] + a.frames["p_bldg"]), p, rtol=1e-9, atol=1e-15
    )
    np.testing.assert_allclose(
        _year(a.frames["w_base"] + a.frames["w_bldg"]), work, rtol=1e-9, atol=1e-15
    )
    bldg = a.components["elec_buildings"] + a.components["fuel_buildings"]
    np.testing.assert_allclose(_year(a.frames["p_bldg"]), bldg, rtol=1e-9, atol=1e-15)


def test_monthly_frames_follow_each_countrys_sector_shape(grid):
    a = h.allocate(_energy(), grid, _proxies(), _monthly())
    fuel = (a.frames["p_bldg"] * AREA).reshape(12, -1).sum(axis=1)
    # Aland's fuel in buildings: three times as much in each winter month as in summer
    # (its electricity follows the flat power sector, so compare the fuel part on its own).
    jan, jul = fuel[0], fuel[6]
    assert jan > jul
    flat = h.allocate(_energy(), grid, _proxies())  # no monthly data: every month alike
    np.testing.assert_allclose(flat.frames["p_base"][0], flat.frames["p_base"][6])
    assert flat.report["monthly_basis"] == "flat"


# ---- a day and a frame -----------------------------------------------------------------


def test_static_round_trip_and_its_year_frame(tmp_path):
    write_static(tmp_path, t_normal=280.0)
    s = h.HumanStatic.load(tmp_path)
    assert s.year == 2024 and s.label == "2024 energy use" and s.t_normal.shape == (12, 360, 720)
    p = sum(s.year_frame()[:2])
    assert h.world_tw(p) == pytest.approx(18.0, rel=1e-5)


def test_a_milestone_24_file_without_frames_is_not_used(tmp_path):
    (tmp_path / "human").mkdir()
    xr.Dataset(
        {"losses_fossil": (("lat", "lon"), np.zeros((360, 720)))}, attrs={"year": 2024}
    ).to_netcdf(tmp_path / "human" / "human_2024.nc")
    assert h.HumanStatic.load(tmp_path) is None


def test_a_cold_day_raises_the_buildings_part_and_nothing_else(tmp_path):
    frames = write_static(tmp_path, t_normal=275.0)
    s = h.HumanStatic.load(tmp_path)
    bld = np.full((360, 720), 2.0)
    typical = h.day_layers(s, date(2026, 1, 10), np.full((360, 720), 275.0), bld)
    cold = h.day_layers(s, date(2026, 1, 10), np.full((360, 720), 265.0), bld)
    p0, p1 = typical["human_q"].values.values, cold["human_q"].values.values
    base = frames["p_base"][0]
    assert np.all(p1 > p0)
    w = d.weather_factor(np.array(265.0), np.array(275.0))
    np.testing.assert_allclose(p1, base + frames["p_bldg"][0] * w, rtol=1e-6)
    heat = cold["human_heat"].values.values
    np.testing.assert_allclose(cold["human_work"].values.values + heat, p1, rtol=1e-6)
    np.testing.assert_allclose(cold["human_ratio"].values.values, p1 / 2.0, rtol=1e-6)


def test_without_normals_a_day_is_its_typical_month(tmp_path):
    frames = write_static(tmp_path)
    s = h.HumanStatic.load(tmp_path)
    layers = h.day_layers(s, date(2026, 8, 1), np.full((360, 720), 250.0), np.full((360, 720), 1.0))
    np.testing.assert_allclose(
        layers["human_q"].values.values, frames["p_base"][7] + frames["p_bldg"][7], rtol=1e-6
    )


def test_an_implausible_world_total_is_refused(tmp_path):
    write_static(tmp_path, world_tw=180.0)
    s = h.HumanStatic.load(tmp_path)
    with pytest.raises(ValueError, match="TW"):
        h.day_layers(s, date(2026, 8, 1), np.full((360, 720), 290.0), np.ones((360, 720)))


def test_for_build_starts_on_the_start_date_and_never_fails_the_build(tmp_path):
    bld, skt = np.ones((360, 720)), np.full((360, 720), 290.0)
    assert h.for_build(date(2026, 8, 1), skt, bld, tmp_path) == {}  # no static file yet
    write_static(tmp_path)
    assert h.for_build(date(2026, 7, 27), skt, bld, tmp_path) == {}
    assert set(h.for_build(date(2026, 7, 28), skt, bld, tmp_path)) == set(HUMAN)
    write_static(tmp_path, world_tw=180.0)  # replaced: the cache notices
    logs = []
    assert h.for_build(date(2026, 7, 28), skt, bld, tmp_path, logs.append) == {}
    assert "left out" in logs[0]


def test_frame_layers_ratio_masks_calm_cells(tmp_path):
    write_static(tmp_path)
    s = h.HumanStatic.load(tmp_path)
    bld = np.full((360, 720), 2.0)
    bld[:10] = 0.001
    f = h.frame_layers(s, "year", bld)
    codes = h.layer_codes(f)
    assert np.all(codes["human_ratio"][:10] == MASKED)
    assert np.all(codes["human_q"] >= 2)


# ---- the build, the published data root and the store ----------------------------------


def test_build_date_adds_the_human_layers_when_there_are_grids(tmp_path):
    from pipeline import run

    work, out = tmp_path / "work", tmp_path / "out"
    write_static(work, t_normal=300.0)
    ds = synthetic_tidy(tsr=240.0)
    ds.attrs["date"] = "2026-08-01"
    ds.to_netcdf(work / "tidy_2026-08-01.nc")
    assert run.build_date(date(2026, 8, 1), tmp_path / "raw", work, out) == []
    for lid in HUMAN:
        assert (out / "fields" / "2026-08-01" / f"{lid}.png").is_file()
    tile = pts.read_tile((out / "points" / "2026-08-01" / "5_5.bin").read_bytes())
    assert np.all(tile["human_heat"] >= 2)
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(HUMAN) <= set(manifest["built_layers"])


def _published_out(root, dates, with_clim=True):
    """A data root as published before milestone 25: diss_bl maps, legacy point chunks."""
    out = root / "out"
    for day in dates:
        (out / "fields" / day).mkdir(parents=True)
        (out / "fields" / day / "diss_bl.png").write_bytes(scalar_png(codes_of("diss_bl", 2.0)))
        legacy_tiles(out / "points" / day, {"t_skin": codes_of("t_skin", 280.0)})
    from pipeline.publish import build_manifest

    if with_clim:
        for frame in h.CLIM_FRAMES:
            (out / "clim" / frame).mkdir(parents=True)
            (out / "clim" / frame / "diss_bl.png").write_bytes(scalar_png(codes_of("diss_bl", 1.0)))
            legacy_tiles(out / "clim" / "points" / frame, {"t_skin": codes_of("t_skin", 285.0)})
        (out / "clim" / "clim.json").write_text(
            json.dumps({"period": "1991-2020", "layers": ["diss_bl"]})
        )
    clim = json.loads((out / "clim" / "clim.json").read_text()) if with_clim else None
    m = build_manifest(dates, "2026-11-06T00:00:00Z", ["diss_bl"], clim)
    (out / "manifest.json").write_text(json.dumps(m))
    return out


def test_apply_to_out_adds_the_layers_from_the_start_date_and_the_climate_frames(tmp_path):
    work = tmp_path / "work"
    write_static(work)  # no normals yet: made from the climate point chunks
    out = _published_out(tmp_path, ["2026-07-27", "2026-07-28", "2026-07-29"])
    counts = h.apply_to_out(out, work, log=lambda m: None)
    assert counts["dates"] == 2 and counts["frames"] == 13 and counts["skipped"] == []
    assert not (out / "fields" / "2026-07-27" / "human_q.png").exists()
    old = (out / "points" / "2026-07-27" / "0_0.bin").read_bytes()
    assert pts.tile_fields(old) == pts.LEGACY_POINT_FIELDS  # untouched before the start
    for day in ("2026-07-28", "2026-07-29"):
        for lid in HUMAN:
            assert (out / "fields" / day / f"{lid}.png").is_file()
        tile = pts.read_tile((out / "points" / day / "3_4.bin").read_bytes())
        assert np.all(tile["human_q"] >= 2) and np.all(
            tile["t_skin"] == codes_of("t_skin", 280.0)[0, 0]
        )
    # The normals came from the climate frames' t_skin (285 K).
    s = h.HumanStatic.load(work)
    np.testing.assert_allclose(s.t_normal, 285.0, atol=0.02)
    # Climate frames: maps, point chunks, series, and the index with its human block.
    for frame in h.CLIM_FRAMES:
        q = png_to_ints((out / "clim" / frame / "human_q.png").read_bytes())
        assert np.all(q >= 2)
    tile = pts.read_tile((out / "clim" / "points" / "07" / "0_0.bin").read_bytes())
    assert np.all(tile["human_ratio"] >= 2)
    series = (out / "clim" / "series" / "human_heat" / "0_0.bin").read_bytes()
    assert len(series) == 12 * 400 * 2
    assert len((out / "clim" / "year" / "series" / "human_heat" / "0_0.bin").read_bytes()) == 800
    index = json.loads((out / "clim" / "clim.json").read_text())
    assert index["layers"] == ["diss_bl", *HUMAN]
    assert index["human"]["label"] == "2024 energy use"
    # The daily series and the manifest, last.
    dates, codes = pts.read_series((out / "series" / "human_q" / "0_0.bin").read_bytes())
    assert dates == ["2026-07-27", "2026-07-28", "2026-07-29"]
    assert np.all(codes[0] == NODATA) and np.all(codes[1:] >= 2)
    m = json.loads((out / "manifest.json").read_text())
    assert set(HUMAN) <= set(m["built_layers"]) and "diss_bl" in m["built_layers"]
    assert m["layers"]["human_q"]["climate_label"] == "2024 energy use"
    assert m["clim"]["human"]["year"] == 2024
    # A second run has nothing left to do.
    again = h.apply_to_out(out, work, log=lambda m: None)
    assert again["dates"] == 0


def test_apply_to_out_without_a_climatology_still_does_the_dates(tmp_path):
    work = tmp_path / "work"
    write_static(work)
    out = _published_out(tmp_path, ["2026-08-01"], with_clim=False)
    logs = []
    counts = h.apply_to_out(out, work, log=logs.append)
    assert counts["dates"] == 1 and counts["frames"] == 0
    assert any("weather factor is 1" in m for m in logs)


def test_apply_to_out_needs_the_grids(tmp_path):
    with pytest.raises(FileNotFoundError, match="human-static"):
        h.apply_to_out(_published_out(tmp_path, ["2026-08-01"]), tmp_path / "work")


def test_the_daily_job_downloads_the_grids_and_the_cli_puts_them_there(tmp_path, capsys):
    from pipeline import deploy
    from pipeline.cli import main
    from pipeline.store import LocalStore

    work = tmp_path / "work"
    write_static(work, t_normal=280.0)
    out = _published_out(tmp_path, ["2026-08-01"])
    bucket = tmp_path / "bucket"
    assert main([
        "human", "--out", str(out), "--work", str(work), "--store", f"file://{bucket}",
    ]) == 0  # fmt: skip
    assert "1 dates, 13 climate frames" in capsys.readouterr().out
    store = LocalStore(bucket)
    assert set(store.list("state/human/")) == {
        "state/human/human_2024.nc",
        "state/human/t_normal.nc",
    }
    deploy.upload(store, out)
    fresh = tmp_path / "runner"
    deploy.download_state(store, fresh / "raw", fresh / "out", work=fresh / "work")
    s = h.HumanStatic.load(fresh / "work")
    assert s is not None and s.t_normal is not None
    # ... and the runner's copy of the published human maps comes down with the others.
    assert (fresh / "out" / "fields" / "2026-08-01" / "human_q.png").is_file()


def _half_degree_months(path, value, months=12):
    lat = 89.75 - 0.5 * np.arange(d.NLAT)
    lon = -179.75 + 0.5 * np.arange(d.NLON)
    data = np.full((months, d.NLAT, d.NLON), value, dtype="float32")
    ds = xr.Dataset(
        {"emissions": (("time", "lat", "lon"), data, {"units": "Tonnes"})},
        coords={"lat": lat, "lon": lon, "time": np.arange(months)},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path, encoding={"emissions": {"zlib": True}})


def test_fetched_edgar_is_reduced_to_half_degree_years_and_reads_the_same(tmp_path):
    import io
    import zipfile

    src = tmp_path / "src"
    for y in (2022, 2023):
        _half_degree_months(src / f"EDGAR_2024_GHG_CO2_{y}_bkl_BUILDINGS_emi.nc", float(y - 2021))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in src.iterdir():
            z.write(p, f"bkl_BUILDINGS/{p.name}")

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(url, timeout):
        return Resp(buf.getvalue() if url.endswith(".zip") else b"x")

    inputs = tmp_path / "in"
    h.fetch_inputs(inputs, opener=opener)
    names = sorted(p.name for p in (inputs / "edgar" / "BUILDINGS").iterdir())
    assert names == [
        "EDGAR_reduced_CO2_2022_BUILDINGS_0p5.nc",
        "EDGAR_reduced_CO2_2023_BUILDINGS_0p5.nc",
    ]  # fmt: skip  (the originals are gone)
    monthly, used = h.load_edgar_monthly(inputs / "edgar")
    assert used == [2022, 2023]
    np.testing.assert_allclose(monthly["buildings"], 1.0 + 2.0)
    annual, year = h.load_edgar(inputs / "edgar", 2024)
    assert year == 2023
    np.testing.assert_allclose(annual["buildings"], 12 * 2.0)


def test_human_with_a_store_takes_grids_built_elsewhere(tmp_path, capsys):
    from pipeline.cli import main
    from pipeline.store import LocalStore

    built = tmp_path / "actions-work"
    write_static(built)
    store = LocalStore(tmp_path / "bucket")
    h.upload_static(store, built, log=lambda m: None)
    out = _published_out(tmp_path, ["2026-08-01"])
    laptop = tmp_path / "laptop-work"
    url = f"file://{tmp_path / 'bucket'}"
    assert main(["human", "--out", str(out), "--work", str(laptop), "--store", url]) == 0
    assert (laptop / "human" / "human_2024.nc").is_file()
    assert (out / "fields" / "2026-08-01" / "human_heat.png").is_file()
    # ... and the normals it made go back up for the daily job.
    assert "state/human/t_normal.nc" in store.list("state/human/")
