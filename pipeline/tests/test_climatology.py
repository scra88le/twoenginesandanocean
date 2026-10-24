import json
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from _helpers import synthetic_tidy

from pipeline import climatology as clim
from pipeline import run
from pipeline.derived import SIGMA, compute_layers
from pipeline.encode import MASKED, decode, png_to_ints
from pipeline.layers import LAYERS

LAT = np.linspace(90, -90, 721)
LON = np.arange(1440) * 0.25
# CDS netcdf names: the vertical integrals come as vike / vited.
NC_NAMES = {"p59.162": "vike", "p86.162": "vited"}
VALUES = {  # raw monthly means: accumulations are J m-2 (or m) per day
    "tsr": 240.0 * 86400, "ttr": -240.0 * 86400, "ssr": 160.0 * 86400, "slhf": -80.0 * 86400,
    "sshf": -20.0 * 86400, "bld": 2.0 * 86400, "tp": 0.003, "skt": 288.0, "tcwv": 25.0,
    "p59.162": 2.0e6, "p86.162": 0.0, "lsm": 1.0,
}  # fmt: skip


def write_chunk(path, months, tmp, scale=lambda t: 1.0):
    """A zip like a CDS result: instantaneous and accumulated fields in two members."""
    times = pd.to_datetime(months)
    members = {"data_stream-moda_stepType-avgua.nc": [], "data_stream-moda_stepType-avgad.nc": []}
    for k in clim.CLIM_KEYS:
        acc = k in ("tsr", "ttr", "ssr", "slhf", "sshf", "bld", "tp")
        members[
            "data_stream-moda_stepType-avgad.nc" if acc else "data_stream-moda_stepType-avgua.nc"
        ].append(k)
    with zipfile.ZipFile(path, "w") as zf:
        for member, keys in members.items():
            data = {
                NC_NAMES.get(k, k): (
                    ("valid_time", "latitude", "longitude"),
                    np.stack(
                        [np.full((721, 1440), VALUES[k] * scale(t), "float32") for t in times]
                    ),
                )
                for k in keys
            }
            # As CDS stamps them: accumulations 06:00 on the 1st, other fields 00:00.
            vt = times + pd.Timedelta(hours=6) if "avgad" in member else times
            ds = xr.Dataset(data, coords={"valid_time": vt, "latitude": LAT, "longitude": LON})
            ds["expver"] = ("valid_time", np.array(["0001"] * len(times)))
            f = tmp / member
            ds.to_netcdf(f, encoding={v: {"zlib": True} for v in data})  # constant: tiny
            zf.write(f, member)
    return path


def test_five_year_chunks_cover_1991_to_2020():
    assert clim.year_chunks() == [
        (1991, 1995), (1996, 2000), (2001, 2005), (2006, 2010), (2011, 2015), (2016, 2020)
    ]  # fmt: skip


def test_a_chunk_request_asks_for_every_month_of_its_years():
    spec = clim.chunk_request(1991, 1995)
    r = spec.request
    assert spec.collection_id == "reanalysis-era5-single-levels-monthly-means"
    assert r["year"] == ["1991", "1992", "1993", "1994", "1995"]
    assert len(r["month"]) == 12 and r["product_type"] == ["monthly_averaged_reanalysis"]
    assert "vertical_integral_of_divergence_of_total_energy_flux" in r["variable"]
    assert len(r["variable"]) == len(clim.CLIM_KEYS) == 12
    assert spec.filename == "clim_1991_1995.zip"


def test_vector_layers_have_no_climatology():
    assert {"wind10", "wind100", "jet250", "flux_e"}.isdisjoint(clim.CLIM_LAYERS)
    # 22 natural layers less the 4 vector ones, plus net_sfc
    assert len(clim.CLIM_LAYERS) == 19 and "net_sfc" in clim.CLIM_LAYERS


def test_monthly_sums_convert_regrid_and_add_up_by_calendar_month(tmp_path):
    path = write_chunk(
        tmp_path / "c.zip", ["1991-01-01", "1991-02-01", "1992-01-01"], tmp_path,
        scale=lambda t: 2.0 if t.year == 1992 else 1.0,
    )  # fmt: skip
    sums = clim.monthly_sums(path)
    assert list(sums["count"].values) == [2, 1] + [0] * 10
    assert sums["olr"].shape == (12, 360, 720)
    # January: 1991 (x1) + 1992 (x2); converted to W m-2 and sign-flipped (olr = -ttr)
    assert float(sums["olr"][0, 100, 100]) == pytest.approx(3 * 240.0, rel=1e-5)
    assert float(sums["le"][0, 0, 0]) == pytest.approx(3 * 80.0, rel=1e-5)
    assert float(sums["tsr"][1, 200, 300]) == pytest.approx(240.0, rel=1e-5)
    assert float(sums["p86.162"][0].max()) == 0.0
    assert float(sums["tp"][1, 0, 0]) == pytest.approx(0.003 * 1000 / 86400, rel=1e-5)  # kg m-2 s-1


def test_monthly_sums_reject_a_chunk_missing_a_variable(tmp_path):
    ds = xr.Dataset(
        {"tsr": (("valid_time", "latitude", "longitude"), np.zeros((1, 721, 1440), "float32"))},
        coords={"valid_time": pd.to_datetime(["1991-01-01"]), "latitude": LAT, "longitude": LON},
    )
    f = tmp_path / "only_tsr.nc"
    ds.to_netcdf(f)
    with pytest.raises(ValueError, match="lacks"):
        clim.monthly_sums(f)


def test_climatology_layers_apply_the_formulas_to_monthly_means(tmp_path):
    sums = clim.monthly_sums(write_chunk(tmp_path / "c.zip", ["1991-03-01"], tmp_path))
    march = (sums / sums["count"].where(sums["count"] > 0)).drop_vars("count").isel(month=2)
    layers = clim.climatology_layers(march)
    assert set(layers) == set(clim.CLIM_LAYERS) - {"net_sfc"}  # no `str` in the main part
    assert float(layers["t_emit"].values[0, 0]) == pytest.approx((240.0 / SIGMA) ** 0.25, rel=1e-5)
    assert float(layers["net_toa"].values[0, 0]) == pytest.approx(0.0, abs=1e-4)
    assert float(layers["evap_frac"].values[0, 0]) == pytest.approx(0.8, rel=1e-5)


# ---- publishing and anomalies ---------------------------------------------------------

CONVERTED = (
    "tsr",
    "olr",
    "ssr",
    "le",
    "h",
    "bld",
    "tp",
    "skt",
    "tcwv",
    "p59.162",
    "p86.162",
    "lsm",
)


def write_sums(work, **overrides):
    """Sums files for all six chunks: every month's mean is the synthetic tidy dataset."""
    tidy = synthetic_tidy(**overrides)
    (work / "clim").mkdir(parents=True, exist_ok=True)
    for a, b in clim.year_chunks():
        n = b - a + 1
        dims = ("month", "latitude", "longitude")
        coords = {"month": np.arange(1, 13), "latitude": tidy.latitude, "longitude": tidy.longitude}
        data = {k: (dims, np.repeat(tidy[k].values[None] * n, 12, 0)) for k in CONVERTED}
        ds = xr.Dataset(data, coords=coords)
        ds["count"] = ("month", np.full(12, n))
        ds.to_netcdf(work / "clim" / f"sums_{a}_{b}.nc", encoding={k: {"zlib": True} for k in data})


def test_monthly_means_average_the_chunks(tmp_path):
    write_sums(tmp_path)
    means = clim.monthly_means(tmp_path)
    assert float(means["tsr"][6, 0, 0]) == pytest.approx(SIGMA * 255.0**4)
    assert "count" not in means


def test_monthly_means_need_all_30_years(tmp_path):
    write_sums(tmp_path)
    p = tmp_path / "clim" / "sums_1991_1995.nc"
    ds = xr.load_dataset(p)
    ds["count"] = ("month", np.full(12, 4))
    ds.to_netcdf(p)
    with pytest.raises(ValueError, match="30 years"):
        clim.monthly_means(tmp_path)


def test_build_climatology_publishes_maps_series_and_index(tmp_path):
    work, out = tmp_path / "work", tmp_path / "out"
    write_sums(work)
    n = clim.build_climatology(work, out)
    # 18 layers (net_sfc needs `str`, which isn't there): 13 frames, 12-month and annual series
    assert n == 13 * 18 + 18 * 648 + 18 * 648 + 1
    s = LAYERS["olr"]
    olr = decode(
        png_to_ints((out / "clim" / "07" / "olr.png").read_bytes()), *s.encode, step=s.resolution
    )
    assert olr[0, 0] == pytest.approx(float(synthetic_tidy()["olr"][0, 0]), abs=s.resolution)
    g = png_to_ints((out / "clim" / "07" / "g_max.png").read_bytes())
    assert (g[-1] == MASKED).all()  # land-only layers keep their mask
    tile = (out / "clim" / "series" / "olr" / "0_0.bin").read_bytes()
    assert len(tile) == 12 * 20 * 20 * 2
    index = json.loads((out / "clim" / "clim.json").read_text())
    assert index["period"] == "1991-2020"
    assert index["layers"] == [i for i in clim.CLIM_LAYERS if i != "net_sfc"]
    assert index["frames"] == [f"{m:02d}" for m in range(1, 13)] + ["year"]
    assert not (out / "clim" / "07" / "wind10.png").exists()
    assert (out / "clim" / "year" / "olr.png").is_file()
    year_tile = (out / "clim" / "year" / "series" / "olr" / "0_0.bin").read_bytes()
    assert len(year_tile) == 20 * 20 * 2  # one frame; the 12-month series keep their length


def test_anomalies_are_daily_minus_the_months_mean(tmp_path):
    work, out, raw = tmp_path / "work", tmp_path / "out", tmp_path / "raw"
    write_sums(work, tsr=240.0, skt=295.0)  # the climatology is 5 K cooler at the surface
    clim.build_climatology(work, out)
    day = date(2026, 7, 15)
    synthetic_tidy(tsr=240.0).assign_attrs(date=day.isoformat()).to_netcdf(work / f"tidy_{day}.nc")
    assert run.build_date(day, raw, work, out) == []
    folder = out / "fields" / day.isoformat()
    # net_sfc has no climatology (no `str` yet) and the date has no lw_up: neither has an anomaly
    expected = {f"{k}_anom.png" for k in clim.CLIM_LAYERS if k != "net_sfc"}
    assert expected <= {p.name for p in folder.iterdir()}
    assert not (folder / "wind10_anom.png").exists()
    s = LAYERS["olr"]
    anom = decode(
        png_to_ints((folder / "olr_anom.png").read_bytes()),
        *s.anomaly_encode,
        step=s.anomaly_resolution,
    )
    assert np.nanmax(np.abs(anom)) <= s.resolution  # same OLR as the climatology
    c = LAYERS["carnot"]
    carnot = decode(
        png_to_ints((folder / "carnot_anom.png").read_bytes()),
        *c.anomaly_encode,
        step=c.anomaly_resolution,
    )
    assert carnot[0, 0] > 1.0  # a warmer surface raises the Carnot limit
    g = png_to_ints((folder / "g_max_anom.png").read_bytes())
    assert (g[-1] == MASKED).all()
    m = json.loads((out / "manifest.json").read_text())
    assert m["clim"]["period"] == "1991-2020"
    assert m["files"]["anomaly"] == "fields/{date}/{layer}_anom.png"
    assert m["layers"]["olr"]["anomaly"] is True and m["layers"]["wind10"]["anomaly"] is False
    assert m["built_layers"] == sorted(m["built_layers"]) and "olr_anom" not in m["built_layers"]


def test_without_a_climatology_dates_build_without_anomalies(tmp_path):
    work, out, raw = tmp_path / "work", tmp_path / "out", tmp_path / "raw"
    work.mkdir()
    day = date(2026, 7, 15)
    synthetic_tidy(tsr=240.0).assign_attrs(date=day.isoformat()).to_netcdf(work / f"tidy_{day}.nc")
    assert run.build_date(day, raw, work, out) == []
    assert not list((out / "fields" / day.isoformat()).glob("*_anom.png"))
    assert json.loads((out / "manifest.json").read_text())["clim"] is None


# ---- the second request set: str and the winds ----------------------------------------


def write_part(path, part, tmp, months=("1991-01-01",), values=None):
    """A zip like the CDS result for `part` (pressure-level data carry a length-1 level)."""
    values = values or {}
    times = pd.to_datetime(list(months))
    pressure = part is clim.PRESSURE
    dims = (
        ("valid_time", "pressure_level", "latitude", "longitude")
        if pressure
        else ("valid_time", "latitude", "longitude")
    )
    shape = (len(times), 1, 721, 1440) if pressure else (len(times), 721, 1440)
    data = {}
    for k in part.keys:
        v = values.get(k, 0.0)
        data[{"u250": "u", "v250": "v"}.get(k, k)] = (dims, np.full(shape, v, "float32"))
    coords = {"valid_time": times, "latitude": LAT, "longitude": LON}
    if pressure:
        coords["pressure_level"] = [250.0]
    ds = xr.Dataset(data, coords=coords)
    f = tmp / "member.nc"
    ds.to_netcdf(f)
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(f, "member.nc")
    return path


def test_the_extra_requests_ask_for_str_and_the_winds():
    spec = clim.chunk_request(1991, 1995, clim.SURFACE)
    assert spec.collection_id == "reanalysis-era5-single-levels-monthly-means"
    assert sorted(spec.request["variable"]) == sorted(
        ["surface_net_thermal_radiation", "10m_u_component_of_wind", "10m_v_component_of_wind",
         "100m_u_component_of_wind", "100m_v_component_of_wind"]
    )  # fmt: skip
    assert spec.filename == "clim_surface_1991_1995.zip"
    spec = clim.chunk_request(1991, 1995, clim.PRESSURE)
    assert spec.collection_id == "reanalysis-era5-pressure-levels-monthly-means"
    assert spec.request["pressure_level"] == ["250"]
    assert sorted(spec.request["variable"]) == ["u_component_of_wind", "v_component_of_wind"]
    assert spec.filename == "clim_pressure_1991_1995.zip"


def test_the_main_request_is_unchanged():
    # Existing keys are never re-fetched: the main request keeps its 12 variables and name.
    assert "pressure_level" not in clim.chunk_request(1991, 1995).request
    assert clim.MAIN.sums_name(1991, 1995) == "sums_1991_1995.nc"


def test_surface_sums_convert_str_to_lw_up_positive_upward(tmp_path):
    path = write_part(
        tmp_path / "s.zip", clim.SURFACE, tmp_path, values={"str": -55.0 * 86400, "u10": 3.0}
    )
    sums = clim.monthly_sums(path, clim.SURFACE)
    assert set(sums.data_vars) == {"lw_up", "u10", "v10", "u100", "v100", "count"}
    assert float(sums["lw_up"][0, 100, 100]) == pytest.approx(55.0, rel=1e-5)
    assert float(sums["u10"][0, 100, 100]) == pytest.approx(3.0, rel=1e-5)


def test_pressure_sums_squeeze_the_level_and_name_the_jet_winds(tmp_path):
    path = write_part(tmp_path / "p.zip", clim.PRESSURE, tmp_path, values={"u250": 20.0})
    sums = clim.monthly_sums(path, clim.PRESSURE)
    assert set(sums.data_vars) == {"u250", "v250", "count"}
    assert float(sums["u250"][0, 0, 0]) == pytest.approx(20.0, rel=1e-5)


def test_a_part_must_have_all_its_variables(tmp_path):
    path = write_part(tmp_path / "p.zip", clim.PRESSURE, tmp_path)
    with pytest.raises(ValueError, match="lacks"):
        clim.monthly_sums(path, clim.SURFACE)


def write_part_sums(work, part, **values):
    """Sums files of an extra part: every month's mean is the given constant per key."""
    (work / "clim").mkdir(parents=True, exist_ok=True)
    names = {"str": "lw_up"}
    for a, b in clim.year_chunks():
        n = b - a + 1
        dims = ("month", "latitude", "longitude")
        tidy = synthetic_tidy()
        coords = {"month": np.arange(1, 13), "latitude": tidy.latitude, "longitude": tidy.longitude}
        data = {
            names.get(k, k): (dims, np.full((12, 360, 720), values.get(k, 0.0) * n))
            for k in part.keys
        }
        ds = xr.Dataset(data, coords=coords)
        ds["count"] = ("month", np.full(12, n))
        ds.to_netcdf(work / "clim" / part.sums_name(a, b))


def test_monthly_means_merge_the_parts_by_key(tmp_path):
    write_sums(tmp_path)
    assert clim.parts_done(tmp_path) == (clim.MAIN,)
    assert "lw_up" not in clim.monthly_means(tmp_path)
    write_part_sums(tmp_path, clim.SURFACE, str=55.0, u10=3.0)
    write_part_sums(tmp_path, clim.PRESSURE, u250=20.0)
    assert clim.parts_done(tmp_path) == clim.PARTS
    means = clim.monthly_means(tmp_path)
    assert float(means["lw_up"][5, 0, 0]) == pytest.approx(55.0)
    assert float(means["u250"][5, 0, 0]) == pytest.approx(20.0)
    assert float(means["tsr"][5, 0, 0]) == pytest.approx(float(synthetic_tidy()["tsr"][0, 0]))


def test_monthly_means_need_the_main_part(tmp_path):
    write_part_sums(tmp_path, clim.SURFACE)
    with pytest.raises(FileNotFoundError):
        clim.monthly_means(tmp_path)


def test_an_incomplete_extra_part_is_ignored_not_half_used(tmp_path):
    write_sums(tmp_path)
    write_part_sums(tmp_path, clim.SURFACE, str=55.0)
    (tmp_path / "clim" / clim.SURFACE.sums_name(2016, 2020)).unlink()
    assert clim.parts_done(tmp_path) == (clim.MAIN,)
    assert "lw_up" not in clim.monthly_means(tmp_path)


# ---- the annual frame -----------------------------------------------------------------


def test_the_annual_mean_of_a_linear_input_is_the_day_weighted_mean_of_the_months():
    tidy = synthetic_tidy()
    months = np.arange(1, 13)
    values = months.astype(float)  # January 1 ... December 12
    grid = np.broadcast_to(values[:, None, None], (12, 360, 720))
    ds = xr.Dataset(
        {"olr": (("month", "latitude", "longitude"), grid)},
        coords={"month": months, "latitude": tidy.latitude, "longitude": tidy.longitude},
    )
    expected = float((values * clim.MONTH_DAYS).sum() / clim.MONTH_DAYS.sum())
    assert float(clim.annual_mean(ds)["olr"][0, 0]) == pytest.approx(expected)
    assert expected != pytest.approx(values.mean())  # the weights matter
    assert clim.MONTH_DAYS.sum() == pytest.approx(365.25)


def test_a_derived_annual_layer_uses_annual_mean_inputs_not_the_mean_of_derived_maps(tmp_path):
    # t_emit = (OLR / sigma)^(1/4) is concave: the mean of monthly t_emit is below the t_emit
    # of the mean OLR. The annual frame must be the second.
    work = tmp_path
    (work / "clim").mkdir(parents=True)
    tidy = synthetic_tidy()
    olr = np.where(np.arange(1, 13) % 2 == 0, 150.0, 330.0)  # alternate months
    for a, b in clim.year_chunks():
        n = b - a + 1
        data = {
            k: ("month latitude longitude".split(), np.repeat(tidy[k].values[None] * n, 12, 0))
            for k in CONVERTED
            if k != "olr"
        }
        data["olr"] = (
            ("month", "latitude", "longitude"),
            olr[:, None, None] * n * np.ones((12, 360, 720)),
        )
        ds = xr.Dataset(
            data,
            coords={"month": np.arange(1, 13), "latitude": tidy.latitude,
                    "longitude": tidy.longitude},
        )  # fmt: skip
        ds["count"] = ("month", np.full(12, n))
        ds.to_netcdf(work / "clim" / f"sums_{a}_{b}.nc")
    means = clim.monthly_means(work)
    months = [float(clim.climatology_layers(means.isel(month=m))["t_emit"].values[0, 0])
              for m in range(12)]  # fmt: skip
    year = float(clim.climatology_layers(clim.annual_mean(means))["t_emit"].values[0, 0])
    olr_year = float((olr * clim.MONTH_DAYS).sum() / clim.MONTH_DAYS.sum())
    assert year == pytest.approx((olr_year / SIGMA) ** 0.25)
    mean_of_derived = float((np.array(months) * clim.MONTH_DAYS).sum() / clim.MONTH_DAYS.sum())
    assert year > mean_of_derived + 1.0


def test_the_annual_frame_has_its_own_radiative_temperature(tmp_path):
    # Constant fields: the annual frame's carnot uses the annual <tsr>, like every month.
    work, out = tmp_path / "work", tmp_path / "out"
    write_sums(work, tsr=240.0)
    clim.build_climatology(work, out)
    s = LAYERS["carnot"]
    year = decode(
        png_to_ints((out / "clim" / "year" / "carnot.png").read_bytes()), *s.encode,
        step=s.resolution,
    )  # fmt: skip
    t_r = (240.0 / SIGMA) ** 0.25
    assert year[0, 0] == pytest.approx(100 * (300.0 - t_r) / 300.0, abs=s.resolution)
    index = json.loads((out / "clim" / "clim.json").read_text())
    assert index["radiative"]["year"] == {"asr": 240.0, "t_r": round(t_r, 2)}
    assert set(index["radiative"]) == set(index["frames"])


def test_net_sfc_is_published_once_str_has_arrived(tmp_path):
    work, out = tmp_path / "work", tmp_path / "out"
    write_sums(work)
    write_part_sums(work, clim.SURFACE, str=50.0)
    write_part_sums(work, clim.PRESSURE)
    clim.build_climatology(work, out)
    s = LAYERS["net_sfc"]
    got = decode(
        png_to_ints((out / "clim" / "year" / "net_sfc.png").read_bytes()), *s.encode,
        step=s.resolution,
    )  # fmt: skip
    assert got[0, 0] == pytest.approx(200.0 - 50.0 - 60.0 - 20.0, abs=s.resolution)
    index = json.loads((out / "clim" / "clim.json").read_text())
    assert "net_sfc" in index["layers"]
    assert (out / "clim" / "series" / "net_sfc" / "0_0.bin").is_file()


class FakeCds:
    """Records submissions; a request is `accepted` until the test finishes it."""

    def __init__(self, tmp):
        self.tmp, self.requests, self.statuses = tmp, {}, {}

    def submit(self, collection_id, request):
        rid = f"r{len(self.requests) + 1}"
        self.requests[rid], self.statuses[rid] = (collection_id, request), "accepted"

        class R:
            request_id = rid

        return R()

    def get_remote(self, rid):
        fake = self

        class Remote:
            status = fake.statuses[rid]

            def download(self, target):
                collection, _ = fake.requests[rid]
                part = clim.PRESSURE if "pressure" in collection else clim.SURFACE
                write_part(fake.tmp / "made.zip", part, fake.tmp, values={"str": -1.0})
                (fake.tmp / "made.zip").replace(target)

        return Remote()


def test_the_extra_parts_queue_at_most_two_per_dataset(tmp_path):
    work, raw = tmp_path / "work", tmp_path / "raw"
    write_sums(work)  # the main part is in: only the extras are requested
    c = FakeCds(tmp_path)
    pending = clim.fetch_chunks(c, raw, work)
    kinds = sorted(r[0] for r in c.requests.values())
    assert (
        kinds
        == ["reanalysis-era5-pressure-levels-monthly-means"] * 2
        + ["reanalysis-era5-single-levels-monthly-means"] * 2
    )
    assert pending == [
        "clim_pressure_1991_1995.zip", "clim_pressure_1996_2000.zip",
        "clim_surface_1991_1995.zip", "clim_surface_1996_2000.zip",
    ]  # fmt: skip
    clim.fetch_chunks(c, raw, work)  # nothing finished, nothing more to queue
    assert len(c.requests) == 4


def test_a_finished_extra_request_is_reduced_and_the_next_one_queued(tmp_path):
    work, raw = tmp_path / "work", tmp_path / "raw"
    write_sums(work)
    c = FakeCds(tmp_path)
    clim.fetch_chunks(c, raw, work)
    first = next(r for r, (cid, _) in c.requests.items() if "pressure" in cid)
    c.statuses[first] = "successful"
    pending = clim.fetch_chunks(c, raw, work)
    assert (work / "clim" / "sums_pressure_1991_1995.nc").is_file()
    assert not (raw / "clim" / "clim_pressure_1991_1995.zip").exists()  # download deleted
    assert "clim_pressure_1991_1995.zip" not in pending
    assert "clim_pressure_2001_2005.zip" in pending  # its slot was refilled
    assert len(c.requests) == 5


def test_requests_in_flight_from_before_the_extras_still_resolve(tmp_path):
    # pending.json written by the old code holds only main-part names
    assert clim._part_of("clim_1991_1995.zip") == (clim.MAIN, 1991, 1995)
    assert clim._part_of("clim_surface_1996_2000.zip") == (clim.SURFACE, 1996, 2000)
    assert clim._part_of("clim_pressure_2016_2020.zip") == (clim.PRESSURE, 2016, 2020)


def test_a_layer_without_a_climatology_gets_no_anomaly(tmp_path):
    # A date built with lw_up before the `str` climatology has arrived: net_sfc is a layer but
    # has no 1991-2020 mean, so its anomaly is left out rather than failing the build.
    work, out = tmp_path / "work", tmp_path / "out"
    write_sums(work)
    clim.build_climatology(work, out)
    layers = compute_layers(synthetic_tidy(lw_up=50.0))
    assert "net_sfc" in layers
    files, clipped = clim.encode_anomalies(layers, 7, clim.Climatology(out))
    assert "net_sfc_anom.png" not in files and "olr_anom.png" in files
    assert "net_sfc" not in clipped
