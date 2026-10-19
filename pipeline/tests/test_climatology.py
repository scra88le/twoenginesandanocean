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
from pipeline.derived import SIGMA
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
    assert len(clim.CLIM_LAYERS) == 18  # 22 natural layers less the 4 vector ones


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
    assert set(layers) == set(clim.CLIM_LAYERS)
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
    assert float(means["tsr"][6, 0, 0]) == pytest.approx(300.0)
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
    assert n == 12 * 18 + 18 * 648 + 1
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
    assert index["period"] == "1991-2020" and index["layers"] == list(clim.CLIM_LAYERS)
    assert not (out / "clim" / "07" / "wind10.png").exists()


def test_anomalies_are_daily_minus_the_months_mean(tmp_path):
    work, out, raw = tmp_path / "work", tmp_path / "out", tmp_path / "raw"
    write_sums(work, tsr=240.0, skt=295.0)  # the climatology is 5 K cooler at the surface
    clim.build_climatology(work, out)
    day = date(2026, 7, 15)
    synthetic_tidy(tsr=240.0).assign_attrs(date=day.isoformat()).to_netcdf(work / f"tidy_{day}.nc")
    assert run.build_date(day, raw, work, out) == []
    folder = out / "fields" / day.isoformat()
    assert {f"{k}_anom.png" for k in clim.CLIM_LAYERS} <= {p.name for p in folder.iterdir()}
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
