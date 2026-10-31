"""The AMOC formulas in `pipeline.derived`: limb integrals, depth-mean velocity, overturning."""

import numpy as np
import pytest

from pipeline import derived as d

# A short column: centres at 5, 15, 30, 600 and 1600 m.
DEPTH = np.array([5.0, 15.0, 30.0, 600.0, 1600.0])


def test_level_edges_start_at_the_surface_and_use_midpoints():
    e = d.level_edges(DEPTH)
    assert e.tolist() == pytest.approx([0, 10, 22.5, 315, 1100, 2100])


def test_limb_thickness_splits_the_straddling_level():
    upper = d.limb_thickness(DEPTH, 0, 1000)
    deep = d.limb_thickness(DEPTH, 1000, np.inf)
    assert upper.tolist() == pytest.approx([10, 12.5, 292.5, 685, 0])
    assert deep.tolist() == pytest.approx([0, 0, 0, 100, 1000])
    assert (upper + deep).sum() == pytest.approx(d.level_edges(DEPTH)[-1])


def test_limb_transport_integrates_and_stops_at_the_sea_floor():
    # Two columns: 1 m/s everywhere, and a shallow one with the bottom two levels dry (NaN).
    u = np.ones((5, 2))
    v = np.full((5, 2), -0.5)
    u[3:, 1] = v[3:, 1] = np.nan
    (uu, vu, hu), (ud, vd, hd) = d.limb_transports(u, v, DEPTH, ((0, 1100), (1100, np.inf)))
    assert uu.tolist() == pytest.approx([1100, 315])
    assert vu.tolist() == pytest.approx([-550, -157.5])
    assert hu.tolist() == pytest.approx([1100, 315])
    assert ud.tolist() == pytest.approx([1000, 0])
    assert hd.tolist() == pytest.approx([1000, 0])


def test_limb_transport_reads_one_level_at_a_time():
    class Levels:  # stands in for a lazily loaded netCDF variable
        def __init__(self, a):
            self.a, self.reads = a, []

        def __len__(self):
            return len(self.a)

        def __getitem__(self, k):
            self.reads.append(k)
            return self.a[k]

    u = Levels(np.ones((5, 3)))
    v = Levels(np.zeros((5, 3)))
    ((uu, _, _),) = d.limb_transports(u, v, DEPTH, ((0, 20),))
    assert uu.tolist() == pytest.approx([20, 20, 20])
    assert u.reads == [0, 1]  # levels wholly below the limb are never read


def test_depth_mean_velocity_masks_thin_water():
    uu = np.array([200.0, 5.0, 0.0])
    vv = np.array([-100.0, 5.0, 0.0])
    h = np.array([1000.0, 20.0, 0.0])
    ub, vb, masked = d.depth_mean_velocity(uu, vv, h, min_thickness=50)
    assert ub[0] == pytest.approx(0.2) and vb[0] == pytest.approx(-0.1)
    assert masked.tolist() == [False, True, True]
    assert np.isnan(ub[1:]).all()


def test_overturning_is_zero_at_the_surface_and_peaks_at_the_reversal():
    # Northward 0.1 m/s above 1100 m, southward below, across a 10-point section at 26.5 N.
    lon = -60 + np.arange(10) / 12
    v = np.where(d.level_edges(DEPTH)[1:, None] <= 1100, 0.1, -0.1) * np.ones((5, 10))
    edges, psi = d.overturning(v, DEPTH, lon, 26.5)
    dx = d.EARTH_RADIUS * np.cos(np.deg2rad(26.5)) * np.deg2rad(1 / 12)
    assert psi[0] == 0
    strength, z = d.amoc_strength(edges, psi)
    assert z == pytest.approx(1100)
    assert strength == pytest.approx(10 * dx * 0.1 * 1100 / d.SVERDRUP)
    assert psi[-1] == pytest.approx(10 * dx * 0.1 * (1100 - 1000) / d.SVERDRUP)


def test_overturning_treats_land_and_sea_floor_as_no_flow():
    lon = np.array([0.0, 1 / 12])
    v = np.array([[1.0, np.nan]] + [[np.nan, np.nan]] * 4)
    _, psi = d.overturning(v, DEPTH, lon, 0.0)
    dx = d.EARTH_RADIUS * np.deg2rad(1 / 12)
    assert psi.tolist() == pytest.approx([0] + [10 * dx / d.SVERDRUP] * 5)


def test_section_transport_sums_across_the_section():
    lon = -60 + np.arange(4) / 12
    vv = np.array([1000.0, np.nan, 500.0, 0.0])
    dx = d.EARTH_RADIUS * np.cos(np.deg2rad(26.5)) * np.deg2rad(1 / 12)
    assert d.section_transport(vv, lon, 26.5) == pytest.approx(1500 * dx / d.SVERDRUP)
