"""All physics formulas for the map. The front end only decodes and displays.

Inputs are the converted, sign-flipped daily fields from `pipeline.convert` on the 0.5 degree
cell-centred grid (360 x 720, lat 89.75 -> -89.75, lon -179.75 -> 179.75), in W m-2 and K.
Nothing here negates an input.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import xarray as xr

SIGMA = 5.670374e-8  # Stefan-Boltzmann, W m-2 K-4
G = 9.81  # m s-2
EARTH_RADIUS = 6.371e6  # m
SECONDS_PER_DAY = 86_400

H_LIFT_M = 3000.0  # lifting height for p_lift; shown in the info panel
SMOOTH_LENGTH_M = 100e3  # diffusion length for div_e (tuned 2026-10-18); shown in the info panel
T_E_CLIP_K = (230.0, 290.0)  # T_e range used in k_r
LAND_THRESHOLD = 0.5  # lsm >= this is land
MIN_TURBULENT_FLUX = 10.0  # W m-2; below this evap_frac is masked
MIN_SURFACE_SOLAR = 10.0  # W m-2; below this j_ratio is masked (J_opt -> 0)
MIN_DISSIPATION = 0.01  # W m-2; below this human_ratio is masked


# ---- point formulas --------------------------------------------------------------------


def emission_temperature(olr):
    """T_e = (OLR / sigma)^(1/4), K."""
    return (olr / SIGMA) ** 0.25


def carnot_efficiency(t_s, t_e):
    """eta_C = (T_s - T_e) / T_s as a fraction, clamped at 0. Returns (eta, clamped)."""
    eta = (t_s - t_e) / t_s
    clamped = eta < 0
    return np.where(clamped, 0.0, eta), clamped


def max_power(r_s, t_s, t_e):
    """Kleidon & Renner single-column maximum power. Returns (J_opt, G_max), W m-2.

    R_s = k_r (T_s - T_a) + J and G = J (T_s - T_a) / T_s give G = J (R_s - J) / (k_r T_s),
    which peaks at J_opt = R_s / 2 with G_max = R_s^2 / (4 k_r T_s), where k_r = 4 sigma T_e^3.
    """
    k_r = 4 * SIGMA * np.clip(t_e, *T_E_CLIP_K) ** 3
    return r_s / 2, r_s**2 / (4 * k_r * t_s)


def evaporative_fraction(le, h):
    """EF = LE / (LE + H). Returns (EF, masked); masked where LE + H < 10 W m-2."""
    total = le + h
    masked = total < MIN_TURBULENT_FLUX
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(masked, np.nan, le / total), masked


def lifting_power(precip_kg_m2_s, h_lift=H_LIFT_M):
    """P_lift = P g h_lift, W m-2. Indicative: h_lift is a fixed assumption."""
    return precip_kg_m2_s * G * h_lift


def wind_speed(u, v):
    return np.hypot(u, v)


def human_ratio(q_human, bld):
    """r_H = q_human / D_BL. Returns (ratio, masked); masked where bld < 0.01 W m-2."""
    masked = bld < MIN_DISSIPATION
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(masked, np.nan, q_human / bld), masked


# ---- spherical finite-volume operator --------------------------------------------------
#
# Cell-centred 0.5 degree grid. For row j with edges phi_j (north) and phi_{j+1} (south):
#   area      A_j = a^2 dlam (sin phi_j - sin phi_{j+1})
#   N/S edge  flux = (a cos phi_e dlam) * dchi / (a dphi)  -> coefficient cos phi_e dlam / dphi
#   E/W edge  flux = (a dphi) * dchi / (a cos phi_j dlam)  -> coefficient dphi / (cos phi_j dlam)
# Pole edges have cos = 0, so nothing crosses them. Summing edge fluxes and dividing by the
# area gives a Laplacian whose area integral is exactly zero. Solves use an FFT in longitude
# and a tridiagonal (Thomas) solve in latitude for each zonal wavenumber.

NLAT, NLON = 360, 720
_DPHI = _DLAM = np.deg2rad(0.5)
_PHI = np.deg2rad(89.75 - 0.5 * np.arange(NLAT))
_EDGES = np.deg2rad(90.0 - 0.5 * np.arange(NLAT + 1))
_COS_EDGE = np.cos(_EDGES)
_COS_EDGE[[0, -1]] = 0.0
_C_NS = _COS_EDGE * _DLAM / _DPHI  # (NLAT + 1,)
_C_EW = _DPHI / (np.cos(_PHI) * _DLAM)  # (NLAT,)
_AREA_ROW = EARTH_RADIUS**2 * _DLAM * (np.sin(_EDGES[:-1]) - np.sin(_EDGES[1:]))  # (NLAT,)
_WAVE = 4 * np.sin(np.pi * np.arange(NLON // 2 + 1) / NLON) ** 2  # -FFT of [1, -2, 1]


def cell_areas() -> np.ndarray:
    """Area of each cell, m2, shape (360, 720)."""
    return np.broadcast_to(_AREA_ROW[:, None], (NLAT, NLON)).copy()


def global_mean(x: np.ndarray) -> float:
    return float((x * _AREA_ROW[:, None]).sum() / (_AREA_ROW.sum() * NLON))


def laplacian(chi: np.ndarray) -> np.ndarray:
    """Finite-volume Laplacian on the sphere, units of chi per m2."""
    north = np.vstack([chi[:1], chi[:-1]])  # pole edges have zero coefficient
    south = np.vstack([chi[1:], chi[-1:]])
    east_west = np.roll(chi, -1, axis=1) - 2 * chi + np.roll(chi, 1, axis=1)
    flux = (
        _C_NS[:-1, None] * (north - chi)
        + _C_NS[1:, None] * (south - chi)
        + _C_EW[:, None] * east_west
    )
    return flux / _AREA_ROW[:, None]


def _operator_bands():
    """Tridiagonal bands of the Laplacian for each zonal wavenumber, shape (NLAT, NM)."""
    shape = (NLAT, _WAVE.size)
    lower = np.broadcast_to((_C_NS[:-1] / _AREA_ROW)[:, None], shape).copy()
    upper = np.broadcast_to((_C_NS[1:] / _AREA_ROW)[:, None], shape).copy()
    diag = -((_C_NS[:-1] + _C_NS[1:]) / _AREA_ROW)[:, None] - (_C_EW / _AREA_ROW)[:, None] * _WAVE
    return lower, diag, upper


def _thomas(lower, diag, upper, rhs):
    """Solve tridiagonal systems along axis 0, one per column."""
    n = diag.shape[0]
    cp = np.empty_like(diag)
    dp = np.empty_like(rhs)
    cp[0] = upper[0] / diag[0]
    dp[0] = rhs[0] / diag[0]
    for j in range(1, n):
        denom = diag[j] - lower[j] * cp[j - 1]
        cp[j] = upper[j] / denom
        dp[j] = (rhs[j] - lower[j] * dp[j - 1]) / denom
    x = np.empty_like(rhs)
    x[-1] = dp[-1]
    for j in range(n - 2, -1, -1):
        x[j] = dp[j] - cp[j] * x[j + 1]
    return x


def solve_poisson(src: np.ndarray) -> np.ndarray:
    """chi with laplacian(chi) = src - <src> and <chi> = 0."""
    rhs = np.fft.rfft(src - global_mean(src), axis=1)
    lower, diag, upper = _operator_bands()
    # Wavenumber 0 is singular (chi is defined up to a constant): pin the first row.
    diag[0, 0], upper[0, 0], rhs[0, 0] = 1.0, 0.0, 0.0
    chi = np.fft.irfft(_thomas(lower, diag, upper, rhs), n=NLON, axis=1)
    return chi - global_mean(chi)


def smooth(x: np.ndarray, length_m: float) -> np.ndarray:
    """Implicit diffusion: solve (1 - L^2 del^2) y = x. Isotropic, keeps the global mean.

    A spherical harmonic of degree l is damped by 1 / (1 + L^2 l (l + 1) / a^2).
    """
    if length_m == 0:
        return x.copy()
    lower, diag, upper = _operator_bands()
    l2 = length_m**2
    rhs = np.fft.rfft(x, axis=1)
    y = _thomas(-l2 * lower, 1 - l2 * diag, -l2 * upper, rhs)
    return np.fft.irfft(y, n=NLON, axis=1)


def _northward_edge_gradient(chi: np.ndarray) -> np.ndarray:
    """d chi / dy on the interior latitude edges, shape (NLAT - 1, NLON)."""
    return (chi[:-1] - chi[1:]) / (EARTH_RADIUS * _DPHI)


def divergent_flux(src: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(eastward, northward) components of grad chi at cell centres, laplacian(chi) = src."""
    chi = solve_poisson(src)
    g = _northward_edge_gradient(chi)
    zero = np.zeros((1, NLON))
    edges = np.vstack([zero, g, zero])
    v = 0.5 * (edges[:-1] + edges[1:])
    u = (np.roll(chi, -1, axis=1) - np.roll(chi, 1, axis=1)) / (
        2 * EARTH_RADIUS * np.cos(_PHI)[:, None] * _DLAM
    )
    return u, v


def meridional_transport(src: np.ndarray) -> np.ndarray:
    """Northward transport, W, of the divergent flux across each interior latitude edge."""
    g = _northward_edge_gradient(solve_poisson(src))
    edge_length = EARTH_RADIUS * _COS_EDGE[1:-1] * _DLAM
    return (g * edge_length[:, None]).sum(axis=1)


# ---- layers ----------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerField:
    """One layer for one date, in catalogue units.

    `masked` marks cells the layer deliberately leaves out (ocean for land-only layers,
    threshold masks); NaN in `values` outside the mask means missing data. Vector layers
    also carry their eastward and northward components; `values` is then the magnitude.
    `carnot` cells clamped at zero are exactly 0, which the front end hatches.
    """

    values: xr.DataArray
    masked: xr.DataArray
    u: xr.DataArray | None = None
    v: xr.DataArray | None = None


def compute_layers(
    tidy: xr.Dataset,
    h_lift: float = H_LIFT_M,
    smooth_length_m: float = SMOOTH_LENGTH_M,
) -> dict[str, LayerField]:
    """Every natural layer for one date from a tidy dataset."""
    coords, dims = {"latitude": tidy.latitude, "longitude": tidy.longitude}, (
        "latitude",
        "longitude",
    )
    no_mask = np.zeros((NLAT, NLON), dtype=bool)

    def da(x) -> xr.DataArray:
        return xr.DataArray(np.asarray(x, dtype="float64"), coords=coords, dims=dims)

    def field(x, masked=no_mask, u=None, v=None) -> LayerField:
        masked = np.asarray(masked, dtype=bool) | np.zeros((NLAT, NLON), dtype=bool)
        x = np.where(masked, np.nan, x)
        return LayerField(
            da(x),
            xr.DataArray(masked, coords=coords, dims=dims),
            None if u is None else da(u),
            None if v is None else da(v),
        )

    def get(name):
        return tidy[name].values.astype("float64")

    tsr, olr, ssr, skt = get("tsr"), get("olr"), get("ssr"), get("skt")
    le, h, tp = get("le"), get("h"), get("tp")
    ocean = get("lsm") < LAND_THRESHOLD

    t_e = emission_temperature(olr)
    eta, _ = carnot_efficiency(skt, t_e)
    j_opt, g_max = max_power(ssr, skt, t_e)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_j = (le + h) / j_opt
    ef, ef_masked = evaporative_fraction(le, h)

    div_e = smooth(get("p86.162"), smooth_length_m)
    fu, fv = divergent_flux(div_e)

    layers = {
        "asr_toa": field(tsr),
        "asr_sfc": field(ssr),
        "net_toa": field(tsr - olr),
        "olr": field(olr),
        "t_emit": field(t_e),
        "carnot": field(100 * eta),
        "g_max": field(g_max, ocean),
        "j_conv": field(le + h),
        "j_ratio": field(r_j, ocean | (ssr < MIN_SURFACE_SOLAR)),
        "lh": field(le),
        "sh": field(h),
        "evap_frac": field(ef, ef_masked),
        "ke_col": field(get("p59.162") / 1e6),
        "diss_bl": field(get("bld")),
        "tcwv": field(get("tcwv")),
        "precip": field(tp * SECONDS_PER_DAY),  # kg m-2 s-1 -> mm/day
        "p_lift": field(lifting_power(tp, h_lift)),
        "div_e": field(div_e),
        "flux_e": field(wind_speed(fu, fv), u=fu, v=fv),
    }
    for name, (un, vn) in {
        "wind10": ("u10", "v10"),
        "wind100": ("u100", "v100"),
        "jet250": ("u250", "v250"),
    }.items():
        u, v = get(un), get(vn)
        layers[name] = field(wind_speed(u, v), u=u, v=v)
    return layers
