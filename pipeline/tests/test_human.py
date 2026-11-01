"""`pipeline.human`: national energy -> annual 0.5 degree component grids."""

import csv
import io
import json
import zipfile

import numpy as np
import pytest
import xarray as xr

from pipeline import derived as d
from pipeline import human as h

AREA = d.cell_areas()

OWID_FIELDS = ["country", "year", "iso_code", "population", "primary_energy_consumption"] + list(
    h.OWID_COLUMNS.values()
)


def _row(country, year, iso, **vals):
    r = dict.fromkeys(OWID_FIELDS, "")
    r.update(country=country, year=str(year), iso_code=iso)
    for k, v in vals.items():
        r[h.OWID_COLUMNS.get(k, k)] = str(v)
    return r


def _write_owid(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OWID_FIELDS)
        w.writeheader()
        w.writerows(rows)


FUELS = dict(coal=100, oil=200, gas=50, biofuel=10)


def _owid_rows():
    return [
        _row("World", 2024, "OWID_WRL", coal=130, oil=260, gas=70, biofuel=12, wind=40, hydro=20),
        _row("World", 2025, "OWID_WRL", wind=45),  # electricity only: not a full year
        _row("Aland", 2024, "AAA", **FUELS, wind=30, nuclear=33, hydro=15),
        _row("Beeland", 2024, "BBB", coal=0, oil=0, gas=0, biofuel=0, solar=5),
        # Not reported by the EI: fuel estimated from primary energy or population.
        _row("Ceeland", 2024, "CCC", wind=5),
        _row("Ceeland", 2021, "CCC", primary_energy_consumption=300),
        _row("Kosovo", 2024, "OWID_KOS", population=1_000_000),
        _row("Europe (EI)", 2024, "", coal=999),
    ]


# ---- national energy -------------------------------------------------------------------


def test_latest_full_year_needs_every_fuel(tmp_path):
    rows = _owid_rows()
    assert h.latest_full_year(rows) == 2024


def test_read_owid_keeps_reported_countries_and_world_fuel_totals(tmp_path):
    p = tmp_path / "owid.csv"
    _write_owid(p, _owid_rows())
    e = h.read_owid(p)
    assert e.year == 2024
    assert set(e.twh) == {"AAA", "BBB", "CCC", "KOS"}  # aggregates dropped, Kosovo renamed
    assert e.twh["AAA"]["coal"] == 100 and e.twh["AAA"]["nuclear"] == 33
    assert sorted(e.estimated) == ["CCC", "KOS"]
    for s in d.FUEL_SOURCES:
        assert sum(src[s] for src in e.twh.values()) == pytest.approx(e.world_twh[s])
    # The rest (30 coal) goes 300 : 1 between Ceeland's primary energy and Kosovo's population.
    assert e.twh["CCC"]["coal"] == pytest.approx(30 * 300 / 301)
    assert e.twh["CCC"]["wind"] == 5  # electricity as reported


def test_read_owid_rejects_a_year_without_world_row(tmp_path):
    p = tmp_path / "owid.csv"
    _write_owid(p, _owid_rows())
    with pytest.raises(ValueError):
        h.read_owid(p, year=1990)


# ---- countries -------------------------------------------------------------------------


def _box(code, lon0, lat0, lon1, lat1):
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    return {
        "type": "Feature",
        "properties": {"ISO_A3_EH": code, "ISO_A3": "-99", "ADM0_A3": code},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _sphere_area(lon0, lat0, lon1, lat1):
    return (
        d.EARTH_RADIUS**2
        * np.deg2rad(lon1 - lon0)
        * (np.sin(np.deg2rad(lat1)) - np.sin(np.deg2rad(lat0)))
    )


GEO = {
    "type": "FeatureCollection",
    "features": [
        _box("BBB", 4, 4, 6, 6),  # an enclave, listed first: drawing order is by size
        _box("AAA", 0, 0, 10, 10),
        _box("CCC", -20, 40, -10, 50),
        _box("KOS", 20, 40, 21, 41),
    ],
}


@pytest.fixture(scope="module")
def grid():
    return h.country_grid(GEO)


def _country_area(grid, code):
    return grid.area[grid.country == grid.codes.index(code)].sum()


def test_country_grid_areas_match_the_sphere(grid):
    enclave = _sphere_area(4, 4, 6, 6)
    assert _country_area(grid, "BBB") == pytest.approx(enclave, rel=0.06)
    assert _country_area(grid, "AAA") == pytest.approx(
        _sphere_area(0, 0, 10, 10) - enclave, rel=0.03
    )
    assert _country_area(grid, "CCC") == pytest.approx(_sphere_area(-20, 40, -10, 50), rel=0.03)


def test_land_share_sums_to_one_per_cell(grid):
    s = np.bincount(grid.cell, weights=grid.land_share(), minlength=d.NLAT * d.NLON)
    assert np.allclose(s[grid.cell], 1.0)


def test_feature_code_falls_back_through_the_iso_keys():
    assert h._feature_code({"ISO_A3_EH": "-99", "ISO_A3": "-99", "ADM0_A3": "NOR"}) == "NOR"
    assert h._feature_code({"ISO_A3_EH": "FRA", "ISO_A3": "-99"}) == "FRA"


# ---- proxies ---------------------------------------------------------------------------


def _fine_grid(step=0.1):
    lat = 90 - step / 2 - step * np.arange(int(180 / step))
    lon = -180 + step / 2 + step * np.arange(int(360 / step))
    return lat, lon


def test_to_half_degree_conserves_totals_and_handles_fluxes():
    lat, lon = _fine_grid()
    ones = np.ones((lat.size, lon.size))
    np.testing.assert_allclose(h.to_half_degree(ones, lat, lon, per_area=False), 25.0)
    flux = h.to_half_degree(ones, lat, lon, per_area=True)  # 1 per m2 -> the cell's area
    np.testing.assert_allclose(flux, AREA, rtol=1e-6)


def test_to_half_degree_accepts_0_360_longitudes():
    lat, lon = _fine_grid()
    v = np.zeros((lat.size, lon.size))
    v[0, 0] = 7.0  # lon -179.95 -> 180.05 when shifted
    out = h.to_half_degree(v, lat, (lon + 360) % 360, per_area=False)
    assert out[0, 0] == 7.0 and out.sum() == 7.0


def test_edgar_sector_names():
    assert h._edgar_sector(h.Path("bkl_POWER_INDUSTRY/x_2023.nc")) == "power"
    name = "EDGAR_2024_GHG_CO2_2023_bkl_IND_COMBUSTION_emi.nc"
    assert h._edgar_sector(h.Path(name)) == "industry"
    assert h._edgar_sector(h.Path("v8.0_FT2022_GHG_CO2_2022_TRO_noRES_flx.nc")) == "transport"
    assert h._edgar_sector(h.Path("bkl_BUILDINGS_2023.nc")) == "buildings"
    assert h._edgar_sector(h.Path("bkl_AGRICULTURE_2023.nc")) is None


def _edgar_file(path, value, units, months=12):
    lat, lon = _fine_grid()
    data = np.full((months, lat.size, lon.size), value, dtype="float32")
    ds = xr.Dataset(
        {"emissions": (("time", "lat", "lon"), data, {"units": units})},
        coords={"lat": lat, "lon": lon, "time": np.arange(months)},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path)


def test_load_edgar_sums_months_picks_the_latest_year_and_detects_fluxes(tmp_path):
    power = tmp_path / "e/POWER"
    _edgar_file(power / "EDGAR_2024_GHG_CO2_2022_bkl_POWER_INDUSTRY_emi.nc", 1.0, "Tonnes")
    _edgar_file(power / "EDGAR_2024_GHG_CO2_2023_bkl_POWER_INDUSTRY_emi.nc", 2.0, "Tonnes")
    _edgar_file(tmp_path / "e/BLD/EDGAR_2024_GHG_CO2_2023_bkl_BUILDINGS_flx.nc", 1.0, "kg m-2 s-1")
    _edgar_file(tmp_path / "e/X/EDGAR_2024_GHG_CO2_2030_bkl_TRANSPORT_emi.nc", 1.0, "Tonnes")
    out, year = h.load_edgar(tmp_path / "e", 2024)
    assert year == 2023
    assert set(out) == {"power", "buildings"}
    np.testing.assert_allclose(out["power"], 2.0 * 12 * 25)
    np.testing.assert_allclose(out["buildings"], 12 * AREA, rtol=1e-5)
    assert h.load_edgar(tmp_path / "e", 2000) == ({}, None)


def test_load_plants_bins_capacity_by_kind(tmp_path):
    p = tmp_path / "gppd.csv"
    p.write_text(
        "country,primary_fuel,capacity_mw,latitude,longitude\n"
        "AAA,Nuclear,1000,5.1,5.1\nAAA,Nuclear,500,5.2,5.3\nAAA,Wind,90,5,5\n"
        "AAA,Biomass,10,1.0,1.0\nAAA,Coal,700,bad,1\n"
    )
    out = h.load_plants(p)
    r, c = int((90 - 5.1) / 0.5), int((5.1 + 180) / 0.5)
    assert out["nuclear_plants"][r, c] == 1500
    assert out["nuclear_plants"].sum() == 1500
    assert out["renewable_plants"].sum() == 10
    assert out["fossil_plants"].sum() == 0  # the bad row is skipped


# ---- allocation ------------------------------------------------------------------------


def _energy():
    twh = {
        "AAA": {s: 0.0 for s in d.SOURCES} | dict(FUELS, nuclear=33.0, wind=30.0),
        "BBB": {s: 0.0 for s in d.SOURCES} | {"solar": 5.0},
        "CCC": {s: 0.0 for s in d.SOURCES} | {"oil": 40.0, "hydro": 8.0},
        "ZZZ": {s: 0.0 for s in d.SOURCES} | {"gas": 1.0},  # no polygon: unplaced
    }
    world = {s: sum(t[s] for t in twh.values()) for s in d.SOURCES}
    return h.NationalEnergy(2024, twh, world)


def _proxies():
    lat = 89.75 - 0.5 * np.arange(d.NLAT)
    lon = -179.75 + 0.5 * np.arange(d.NLON)
    near = lambda la, lo: (np.abs(lat - la) < 1)[:, None] & (np.abs(lon - lo) < 1)[None, :]  # noqa: E731
    p = {k: np.zeros((d.NLAT, d.NLON)) for k in ("power", "industry", "transport", "buildings")}
    p["power"][near(2, 2)] = 4.0
    p["industry"][near(8, 8)] = 3.0
    p["transport"][near(5, 1)] = 2.0
    p["transport"][near(-30, -30)] = 1.0  # open ocean: shipping
    p["buildings"][near(8, 2)] = 1.0
    p["nuclear_plants"] = np.where(near(3, 8), 1.0, 0.0)
    return p


def _integral(field, mask=None):
    f = field * AREA
    return float(f[mask].sum() if mask is not None else f.sum())


def _primary_w(twh):
    return sum(d.direct_equivalent(twh).values()) * 1e12 / d.HOURS_PER_YEAR


def test_allocate_conserves_each_country_and_the_world(grid):
    e = _energy()
    a = h.allocate(e, grid, _proxies())
    p, work, heat = d.cascade(a.components)
    world = sum(_primary_w(t) for c, t in e.twh.items() if c != "ZZZ")
    assert _integral(p) == pytest.approx(world, rel=1e-9)
    assert a.report["unplaced_w"] == {"ZZZ": pytest.approx(_primary_w(e.twh["ZZZ"]))}
    np.testing.assert_allclose(work + heat, p)
    # Beeland (enclave, solar only, no proxies): its own cells hold exactly its power.
    bbb = np.zeros(d.NLAT * d.NLON, bool)
    bbb[grid.cell[grid.country == grid.codes.index("BBB")]] = True
    only_b = bbb & ~np.isin(np.arange(bbb.size), grid.cell[grid.country != grid.codes.index("BBB")])
    assert _integral(p, only_b.reshape(d.NLAT, d.NLON)) <= _primary_w(e.twh["BBB"]) * (1 + 1e-9)


def test_allocate_places_components_by_their_proxies(grid):
    a = h.allocate(_energy(), grid, _proxies())
    c = a.components
    # Fossil plant losses sit where the power-industry emissions are, nuclear at the reactor.
    # (Ceeland has no proxies, so its losses fall back to its land area, far from Aland.)
    aland = np.zeros(d.NLAT * d.NLON, bool)
    aland[grid.cell[grid.country == grid.codes.index("AAA")]] = True
    aland = aland.reshape(d.NLAT, d.NLON)
    assert np.all((c["losses_fossil"] > 0)[aland] == (_proxies()["power"] > 0)[aland])
    assert "AAA" not in a.report["fallbacks"].get("losses_fossil", [])
    assert "CCC" in a.report["fallbacks"]["losses_fossil"]
    assert np.all((c["losses_nuclear"] > 0) == (_proxies()["nuclear_plants"] > 0))
    # Bunkers go to open-ocean transport cells only.
    assert np.all((c["fuel_bunkers"] > 0) == (_proxies()["transport"] > 0) & ~grid.land_cells())
    assert a.report["bunker_basis"].startswith("EDGAR")


def test_allocate_takes_the_bunkers_out_of_oil(grid):
    e = _energy()
    a = h.allocate(e, grid, _proxies())
    bunkers = _integral(a.components["fuel_bunkers"])
    assert 0 < bunkers < sum(t["oil"] for t in e.twh.values()) * 1e12 / d.HOURS_PER_YEAR


def test_allocate_falls_back_to_land_area_and_reports_it(grid):
    a = h.allocate(_energy(), grid, {})  # no proxies at all
    assert "BBB" in a.report["fallbacks"]["elec_buildings"]
    assert sorted(a.report["default_shares"]) == ["AAA", "CCC"]  # countries with fossil fuel
    assert a.report["bunker_basis"].startswith("default")
    p, _, _ = d.cascade(a.components)
    world = sum(_primary_w(t) for c, t in _energy().twh.items() if c != "ZZZ")
    assert _integral(p) == pytest.approx(world, rel=1e-9)


# ---- downloads and the static product --------------------------------------------------


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_inputs_downloads_and_extracts_only_netcdf(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dir/EDGAR_2023_bkl_X.nc", b"nc")
        z.writestr("../../evil.nc", b"bad")
        z.writestr("readme.txt", b"txt")
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return _Resp(buf.getvalue() if url.endswith(".zip") else b"data")

    written = h.fetch_inputs(tmp_path, opener=opener)
    assert len(calls) == len(h.URLS) + len(h.EDGAR_DOWNLOAD)
    assert (tmp_path / "owid-energy-data.csv").read_bytes() == b"data"
    sector = tmp_path / "edgar" / "TRANSPORT"
    assert sorted(p.name for p in sector.iterdir()) == ["EDGAR_2023_bkl_X.nc", "evil.nc"]
    assert not (tmp_path.parent / "evil.nc").exists()
    assert all(p.is_relative_to(tmp_path) for p in written)
    calls.clear()
    h.fetch_inputs(tmp_path, opener=opener)  # everything is there: nothing downloaded
    assert calls == []


def test_build_static_end_to_end_without_edgar(tmp_path):
    _write_owid(tmp_path / "owid-energy-data.csv", _owid_rows())
    (tmp_path / "ne_50m_admin_0_countries.geojson").write_text(json.dumps(GEO))
    (tmp_path / "global_power_plant_database.csv").write_text(
        "country,primary_fuel,capacity_mw,latitude,longitude\nAAA,Nuclear,1000,3,8\n"
    )
    ds, summary = h.build_static(tmp_path)
    assert summary["year"] == 2024 and summary["edgar_year"] is None
    assert set(ds.data_vars) == set(d.COMPONENTS)
    assert summary["useful_work_tw"] + summary["waste_heat_tw"] == pytest.approx(
        summary["primary_tw"]
    )
    assert summary["primary_tw"] + summary["unplaced_tw"] == pytest.approx(
        sum(summary["by_source_tw"].values()), rel=1e-6
    )
    path = h.write_static(ds, summary, tmp_path / "work")
    back = xr.load_dataset(path)
    assert back["losses_nuclear"].attrs["useful_fraction"] == 0.0
    assert json.loads((path.parent / "summary_2024.json").read_text())["year"] == 2024


def test_cli_human_static(tmp_path, capsys):
    from pipeline.cli import main

    inputs = tmp_path / "in"
    inputs.mkdir()
    _write_owid(inputs / "owid-energy-data.csv", _owid_rows())
    (inputs / "ne_50m_admin_0_countries.geojson").write_text(json.dumps(GEO))
    (inputs / "global_power_plant_database.csv").write_text(
        "country,primary_fuel,capacity_mw,latitude,longitude\n"
    )
    assert main(["human-static", "--inputs", str(inputs), "--work", str(tmp_path / "w")]) == 0
    out = capsys.readouterr().out
    assert "human-static 2024: P" in out and "no EDGAR" in out
    assert (tmp_path / "w" / "human" / "human_2024.nc").is_file()
