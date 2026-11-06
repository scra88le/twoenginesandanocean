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
MIN_SURFACE_SOLAR = 10.0  # W m-2; below this j_ratio is masked (J_opt -> 0, ratio explodes)
MIN_DISSIPATION = 0.01  # W m-2; below this human_ratio is masked


# ---- point formulas --------------------------------------------------------------------


def emission_temperature(olr):
    """T_e = (OLR / sigma)^(1/4), K."""
    return (olr / SIGMA) ** 0.25


def radiative_temperature(asr_mean):
    """T_r = (<ASR_TOA> / sigma)^(1/4), K: the radiative temperature of the whole system, from
    the area-weighted global mean of absorbed solar at the top of the atmosphere for the same
    frame (day, month or year). Kleidon's cold side; about 255 K."""
    return (asr_mean / SIGMA) ** 0.25


def radiative_summary(tsr) -> tuple[float, float]:
    """(<ASR_TOA>, T_r) of a frame: the area-weighted global mean of `tsr`, W m-2, and the
    radiative temperature it gives, K. What the manifest publishes and the panels quote."""
    asr = global_mean(np.asarray(tsr, dtype="float64"))
    return asr, float(radiative_temperature(asr))


def carnot_efficiency(t_s, t_cold):
    """eta_C = (T_s - T_cold) / T_s as a fraction, clamped at 0. Returns (eta, clamped).
    The cold side is the radiative temperature T_r."""
    eta = (t_s - t_cold) / t_s
    clamped = eta < 0
    return np.where(clamped, 0.0, eta), clamped


def max_power(r_s, t_s, t_r):
    """Kleidon & Renner single-column maximum power. Returns (J_opt, G_max), W m-2.

    R_s = k_r (T_s - T_a) + J and G = J (T_s - T_a) / T_s give G = J (R_s - J) / (k_r T_s),
    which peaks at J_opt = R_s / 2 with G_max = R_s^2 / (4 k_r T_s), where k_r = 4 sigma T_r^3
    and T_r is the radiative temperature (clipped to 230-290 K, a no-op for the real one).
    """
    k_r = 4 * SIGMA * np.clip(t_r, *T_E_CLIP_K) ** 3
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
    coords, dims = (
        {"latitude": tidy.latitude, "longitude": tidy.longitude},
        (
            "latitude",
            "longitude",
        ),
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
    t_r = radiative_summary(tsr)[1]  # one cold side for the whole frame
    eta, _ = carnot_efficiency(skt, t_r)
    j_opt, g_max = max_power(ssr, skt, t_r)
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
    if "lw_up" in tidy:  # dates built before `str` was fetched have no ocean layer
        layers["net_sfc"] = field(ssr - get("lw_up") - le - h)
    for name, (un, vn) in {
        "wind10": ("u10", "v10"),
        "wind100": ("u100", "v100"),
        "jet250": ("u250", "v250"),
    }.items():
        u, v = get(un), get(vn)
        layers[name] = field(wind_speed(u, v), u=u, v=v)
    return layers


def compute_extras(tidy: xr.Dataset) -> dict[str, LayerField]:
    """Readout-only quantities that aren't map layers: the hot side T_s and J_opt (land only).

    They go into the point chunks next to the layers, so the front end never computes them.
    """
    coords, dims = (
        {"latitude": tidy.latitude, "longitude": tidy.longitude},
        ("latitude", "longitude"),
    )
    skt = tidy["skt"].values.astype("float64")
    ocean = tidy["lsm"].values < LAND_THRESHOLD
    t_r = radiative_temperature(global_mean(tidy["tsr"].values.astype("float64")))
    j_opt, _ = max_power(tidy["ssr"].values.astype("float64"), skt, t_r)

    def field(x, masked):
        masked = np.asarray(masked, dtype=bool)
        return LayerField(
            xr.DataArray(np.where(masked, np.nan, x), coords=coords, dims=dims),
            xr.DataArray(masked, coords=coords, dims=dims),
        )

    return {"t_skin": field(skt, np.zeros_like(ocean)), "j_opt": field(j_opt, ocean)}


# ---- the ocean: the two limbs of the Atlantic overturning (AMOC) -----------------------
#
# Inputs are the Copernicus Marine GLO12 daily-mean currents u, v (m s-1) on the model's own
# depth levels, NaN below the sea floor. At 26.5 N the overturning reverses at about 1100 m
# (RAPID), so the upper limb is the water above AMOC_SPLIT_M and the deep limb the water
# below it. Integrating u and v over a limb gives its transport per metre of width (m2 s-1):
# the map shows where each limb's water goes and how much of it there is.

AMOC_SPLIT_M = 1100.0  # m; depth of the overturning maximum at 26.5 N; shown in the info text
SVERDRUP = 1e6  # m3 s-1


def level_edges(depth) -> np.ndarray:
    """Edges of the model levels from their centres, m: 0 at the surface, midpoints between
    centres, and a bottom edge as far below the last centre as the edge above it is above."""
    z = np.asarray(depth, dtype="float64")
    mid = (z[1:] + z[:-1]) / 2
    return np.concatenate([[0.0], mid, [z[-1] + (z[-1] - mid[-1])]])


def limb_thickness(depth, top: float, bottom: float) -> np.ndarray:
    """How much of each level lies between depths `top` and `bottom`, m, shape (nz,)."""
    e = level_edges(depth)
    return np.clip(np.minimum(e[1:], bottom) - np.maximum(e[:-1], top), 0.0, None)


def limb_transports(u, v, depth, limbs) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Depth-integrated transport of each limb in `limbs` ((top, bottom) pairs, m).

    u, v have the level first and NaN below the sea floor; levels are read one at a time,
    and only if some limb needs them, so a lazily loaded netCDF variable never has to fit in
    memory. Returns one (U, V, H) per limb: U = integral of u dz and V = integral of v dz over
    the limb (m2 s-1, volume transport per metre of width), and H, the thickness of water in
    the limb (m), which is less than the limb where the sea floor cuts it off.
    """
    dz = [limb_thickness(depth, top, bottom) for top, bottom in limbs]
    out: list[list[np.ndarray] | None] = [None] * len(limbs)
    for k in range(len(depth)):
        if not any(t[k] > 0 for t in dz):
            continue
        uk = np.asarray(u[k], dtype="float64")
        vk = np.asarray(v[k], dtype="float64")
        wet = np.isfinite(uk) & np.isfinite(vk)
        uk, vk = np.where(wet, uk, 0.0), np.where(wet, vk, 0.0)
        for i, t in enumerate(dz):
            if t[k] == 0:
                continue
            if out[i] is None:
                out[i] = [np.zeros(uk.shape) for _ in range(3)]
            acc = out[i]
            acc[0] += uk * t[k]
            acc[1] += vk * t[k]
            acc[2] += wet * t[k]
    if all(a is None for a in out):
        shape = np.shape(np.asarray(u[0]))
        return [tuple(np.zeros(shape) for _ in range(3)) for _ in limbs]
    shape = next(a for a in out if a is not None)[0].shape
    return [tuple(a) if a is not None else tuple(np.zeros(shape) for _ in range(3)) for a in out]


def overturning_part(limbs):
    """Remove the depth-uniform flow from limbs that together span the water column.

    `limbs` is a list of (U, V, H) as `limb_transports` returns. The wind-driven gyres and the
    Gulf Stream's recirculation are close to depth-uniform, so they put the same velocity
    (U_total / H_total) into every limb; the overturning is the part where the limbs differ
    (the upper limb north, the deep limb south). Subtracting H_limb x the whole column's mean
    velocity leaves a transport per limb that sums to zero over the column. H is unchanged;
    where there is no water the transport is zero.
    """
    h_all = sum(np.asarray(h, dtype="float64") for _, _, h in limbs)
    u_all = sum(np.asarray(uu, dtype="float64") for uu, _, _ in limbs)
    v_all = sum(np.asarray(vv, dtype="float64") for _, vv, _ in limbs)
    with np.errstate(divide="ignore", invalid="ignore"):
        ub = np.where(h_all > 0, u_all / h_all, 0.0)
        vb = np.where(h_all > 0, v_all / h_all, 0.0)
    return [(uu - h * ub, vv - h * vb, h) for uu, vv, h in limbs]


def masked_smooth(fields, valid, sigma_cells: float):
    """Gaussian-smooth each 2-D field over the cells where `valid` is true.

    Normalised convolution: smooth(field x valid) / smooth(valid), so land and cells outside the
    box neither pull values toward zero nor leak into the water. The kernel is separable and cut
    at 3 sigma. Cells that are not valid come back NaN. Returns a list, one array per field.
    """
    valid = np.asarray(valid, dtype=bool)
    r = max(1, int(np.ceil(3 * sigma_cells)))
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sigma_cells) ** 2)
    k /= k.sum()

    def blur(a):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (r, r)
            padded = np.pad(a, pad)
            a = sum(
                k[i] * np.take(padded, np.arange(i, i + a.shape[axis]), axis=axis)
                for i in range(len(k))
            )
        return a

    weight = blur(valid.astype("float64"))
    out = []
    for f in fields:
        f = np.where(valid, np.asarray(f, dtype="float64"), 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            out.append(np.where(valid & (weight > 0), blur(f) / weight, np.nan))
    return out


def depth_mean_velocity(uu, vv, h, min_thickness: float):
    """Depth-mean velocity of a limb, U / H and V / H, m s-1: how fast its water moves.
    Returns (u, v, masked); masked where the limb holds less than `min_thickness` of water."""
    h = np.asarray(h, dtype="float64")
    masked = ~(h >= min_thickness)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(masked, np.nan, uu / h), np.where(masked, np.nan, vv / h), masked


def _section_dx(lon_deg, lat_deg: float) -> float:
    """Width of one grid step along a latitude circle, m (evenly spaced longitudes)."""
    dlam = np.deg2rad(abs(float(lon_deg[1]) - float(lon_deg[0])))
    return EARTH_RADIUS * np.cos(np.deg2rad(lat_deg)) * dlam


def overturning(v, depth, lon_deg, lat_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Overturning streamfunction across a latitude section, Sv, at each level edge.

    psi(z) = sum over the levels above z of (sum over the section of v dx) dz: the northward
    volume transport above depth z, so psi(0) = 0. v is (nz, nx) in m s-1, NaN on land and
    below the sea floor (no flow). Returns (edges in m, psi in Sv)."""
    edges = level_edges(depth)
    per_level = np.nansum(np.asarray(v, dtype="float64"), axis=1) * _section_dx(lon_deg, lat_deg)
    psi = np.concatenate([[0.0], np.cumsum(per_level * np.diff(edges))]) / SVERDRUP
    return edges, psi


def amoc_strength(edges: np.ndarray, psi: np.ndarray) -> tuple[float, float]:
    """The AMOC strength, the maximum of the streamfunction (Sv), and its depth (m)."""
    k = int(np.argmax(psi))
    return float(psi[k]), float(edges[k])


def latitude_overturning(
    v, depth, lat_deg, lon_deg, basin, grid_lat
) -> tuple[np.ndarray, np.ndarray]:
    """The overturning streamfunction of a basin on a latitude-depth section, Sv.

    psi(lat, z) = the northward volume transport of the basin above depth z, summed along the
    latitude circle (`basin` picks the columns). v is (nz, nlat, nlon) in m s-1, NaN on land and
    below the sea floor (no flow), read one level at a time; `basin` is (nlat, nlon) on the same
    grid. Rows of the model are averaged into the bins of `grid_lat` (ascending centres, evenly
    spaced), which smooths eddies without changing the zonal integral's meaning.

    Returns (psi, wet), both (nz, n_lat), one row per level: psi at the level's bottom edge (so
    the maximum over depth is the true maximum of the streamfunction); wet is True where the
    basin holds water at that level and latitude."""
    lat = np.asarray(lat_deg, dtype="float64")
    grid = np.asarray(grid_lat, dtype="float64")
    step = float(grid[1] - grid[0])
    bins = np.rint((lat - grid[0]) / step).astype(int)
    inside = (bins >= 0) & (bins < len(grid))
    dlam = np.deg2rad(abs(float(lon_deg[1]) - float(lon_deg[0])))
    dx = EARTH_RADIUS * np.cos(np.deg2rad(lat)) * dlam
    basin = np.asarray(basin, dtype=bool)
    rows = np.bincount(bins[inside], minlength=len(grid)).astype("float64")
    edges = level_edges(depth)
    nz = len(depth)
    transport = np.zeros((nz, len(grid)))
    wet = np.zeros((nz, len(grid)), dtype=bool)
    for k in range(nz):
        vk = np.asarray(v[k], dtype="float64")
        ok = np.isfinite(vk) & basin
        per_row = np.where(ok, vk, 0.0).sum(axis=1) * dx
        transport[k] = np.bincount(bins[inside], weights=per_row[inside], minlength=len(grid))
        wet[k] = np.bincount(bins[inside], weights=ok.any(axis=1)[inside], minlength=len(grid)) > 0
    transport = np.divide(transport, rows, out=np.zeros_like(transport), where=rows > 0)
    cum = np.vstack([np.zeros(len(grid)), np.cumsum(transport * np.diff(edges)[:, None], axis=0)])
    return cum[1:] / SVERDRUP, wet


def limb_transports_by_latitude(
    psi, depth, split: float = AMOC_SPLIT_M
) -> tuple[np.ndarray, np.ndarray]:
    """The two limbs' net northward transport at every latitude, Sv, from the section's psi.

    `psi` is (nz, n_lat) at the levels' bottom edges (`latitude_overturning`). The upper limb
    is psi at depth `split` (interpolated between the level edges), the deep limb is what
    remains of the column below it: psi at the sea floor minus psi at `split`. Summed across
    the whole basin, the eddies and gyres of a single latitude cancel, which is why this is
    far less noisy than a map of the limbs' flow."""
    psi = np.asarray(psi, dtype="float64")
    edges = level_edges(depth)
    column = np.vstack([np.zeros(psi.shape[1]), psi])  # psi at every edge, 0 at the surface
    upper = np.array([np.interp(split, edges, column[:, j]) for j in range(psi.shape[1])])
    return upper, column[-1] - upper


def section_transport(vv, lon_deg, lat_deg: float) -> float:
    """Northward transport of a limb across a latitude section, Sv, from its depth-integrated
    northward transport per metre V (m2 s-1) along the section; NaN counts as no flow."""
    return float(
        np.nansum(np.asarray(vv, dtype="float64")) * _section_dx(lon_deg, lat_deg) / SVERDRUP
    )


# ---- the technosphere: Kleidon's free-energy cascade -----------------------------------
#
# Humanity's primary power P is free energy taken from the Earth's engines (and from the
# fossil store, which is the biosphere's past output). It is counted direct-equivalent: the
# fuel's energy for fossil fuel and biofuel, the reactor or furnace heat for nuclear and
# thermal renewables, and the electricity itself for wind, sunlight and falling water, which
# arrive as free energy rather than heat. P splits into useful work W_u (exergy delivered at
# end uses) and waste heat; W_u becomes heat too, so all of P ends as heat radiated to space.
#
# The efficiencies are indicative world values (after De Stercke 2014, Paoli & Cullen 2020,
# and the IEA's physical-content conventions), kept here so the info panels quote them.

HOURS_PER_YEAR = 8766.0  # 365.25 days

NUCLEAR_EFFICIENCY = 0.33  # electricity / reactor heat (Energy Institute, IEA)
THERMAL_RENEWABLE_EFFICIENCY = 0.33  # bioenergy and geothermal power, electricity / heat in
FOSSIL_GENERATION_EFFICIENCY = 0.38  # fossil power stations, electricity / fuel, world mean
ELEC_INDUSTRY_SHARE = 0.45  # of delivered electricity; the rest goes to buildings (and other)

SOURCES = (
    "coal", "oil", "gas", "biofuel", "nuclear", "hydro", "wind", "solar", "other_renewable",
)  # fmt: skip
# Sources reported as primary energy (fuel), and as electricity generated.
FUEL_SOURCES = ("coal", "oil", "gas", "biofuel")
FOSSIL_SOURCES = ("coal", "oil", "gas")

# The engine each source draws on. Fossil fuel is the biosphere's stored past output.
SOURCE_ENGINE = {
    "coal": "fossil", "oil": "fossil", "gas": "fossil",
    "biofuel": "biosphere", "other_renewable": "biosphere",
    "hydro": "water", "wind": "atmosphere", "solar": "radiation", "nuclear": "none",
}  # fmt: skip
ENGINES = ("fossil", "biosphere", "water", "atmosphere", "radiation", "none")

# Fossil fuel use by sector (shares from EDGAR's sector emissions, per country).
SECTORS = ("power", "industry", "transport", "buildings")

# The pieces P is made of, each placed on the map where its heat is released.
COMPONENTS = (
    "losses_fossil",  # conversion losses at fossil power stations
    "losses_nuclear",  # at nuclear power stations
    "losses_renewable",  # at bioenergy and geothermal power stations
    "elec_industry",  # delivered electricity, dissipated where it is used
    "elec_buildings",
    "fuel_industry",  # fuel burnt at the point of use
    "fuel_transport",
    "fuel_buildings",
    "fuel_bunkers",  # international aviation and shipping
)

# Useful work (exergy) per unit of each component, final to useful, indicative world values.
USEFUL_FRACTION = {
    "losses_fossil": 0.0,
    "losses_nuclear": 0.0,
    "losses_renewable": 0.0,
    "elec_industry": 0.55,  # motors dominate
    "elec_buildings": 0.30,  # lighting, appliances, low-temperature heat
    "fuel_industry": 0.30,  # process heat
    "fuel_transport": 0.20,  # vehicle engines, tank to wheel
    "fuel_buildings": 0.10,  # low-temperature space and water heat
    "fuel_bunkers": 0.25,  # marine diesels and jet engines
}


def twh_per_year_to_watts(twh):
    """TWh per year -> mean power in W (a year of 365.25 days: 8766 TWh/yr is 1 TW)."""
    x = np.asarray(twh, dtype="float64") * 1e12 / HOURS_PER_YEAR
    return float(x) if x.ndim == 0 else x


def direct_equivalent(sources: dict[str, float]) -> dict[str, float]:
    """Primary power by source, direct-equivalent, from the Energy Institute's columns: primary
    energy for the fuels (coal, oil, gas, biofuel) and electricity generated for the rest.
    Nuclear and thermal renewables count their heat (electricity / efficiency); wind, solar
    and hydro their electricity. Units pass through; missing sources are zero."""
    unknown = set(sources) - set(SOURCES)
    if unknown:
        raise KeyError(f"unknown sources: {sorted(unknown)}")
    p = {s: float(sources.get(s, 0.0)) for s in SOURCES}
    p["nuclear"] /= NUCLEAR_EFFICIENCY
    p["other_renewable"] /= THERMAL_RENEWABLE_EFFICIENCY
    return p


def by_engine(primary: dict[str, float]) -> dict[str, float]:
    """Primary power summed by the engine each source draws on."""
    out = dict.fromkeys(ENGINES, 0.0)
    for s, v in primary.items():
        out[SOURCE_ENGINE[s]] += v
    return out


def plant_split(fuel, efficiency: float):
    """Fuel (or heat) into a power station -> (electricity out, conversion losses)."""
    if not 0.0 <= efficiency <= 1.0:
        raise ValueError(f"efficiency must be in 0-1, got {efficiency}")
    elec = fuel * efficiency
    return elec, fuel - elec


def remove_pro_rata(values: dict[str, float], total: float) -> tuple[dict, dict]:
    """Take `total` from `values` in proportion to each: (kept, taken). Used to move the
    international bunker fuel out of the countries' oil."""
    have = sum(values.values())
    if total > have * (1 + 1e-12):
        raise ValueError(f"cannot take {total} from {have}")
    f = total / have if have > 0 else 0.0
    taken = {k: v * f for k, v in values.items()}
    return {k: v - taken[k] for k, v in values.items()}, taken


def national_components(
    primary: dict[str, float], fossil_shares: dict[str, float] | None
) -> dict[str, float]:
    """A country's direct-equivalent primary power by source -> its components (all but the
    bunkers, which are global). `fossil_shares` splits fossil fuel between power, industry,
    transport and buildings and must sum to 1 (it may be None when there is no fossil fuel).
    Sums to the country's primary power exactly."""
    fossil = sum(primary.get(s, 0.0) for s in FOSSIL_SOURCES)
    if fossil > 0 or fossil_shares is not None:
        if fossil_shares is None or set(fossil_shares) != set(SECTORS):
            raise ValueError(f"fossil_shares needs exactly {SECTORS}")
        if abs(sum(fossil_shares.values()) - 1.0) > 1e-9:
            raise ValueError("fossil_shares must sum to 1")
    shares = fossil_shares or dict.fromkeys(SECTORS, 0.0)

    fossil_elec, losses_fossil = plant_split(fossil * shares["power"], FOSSIL_GENERATION_EFFICIENCY)
    nuclear_elec, losses_nuclear = plant_split(primary.get("nuclear", 0.0), NUCLEAR_EFFICIENCY)
    renew_elec, losses_renew = plant_split(
        primary.get("other_renewable", 0.0), THERMAL_RENEWABLE_EFFICIENCY
    )
    elec = (
        fossil_elec + nuclear_elec + renew_elec
        + primary.get("hydro", 0.0) + primary.get("wind", 0.0) + primary.get("solar", 0.0)
    )  # fmt: skip
    return {
        "losses_fossil": losses_fossil,
        "losses_nuclear": losses_nuclear,
        "losses_renewable": losses_renew,
        "elec_industry": elec * ELEC_INDUSTRY_SHARE,
        "elec_buildings": elec * (1 - ELEC_INDUSTRY_SHARE),
        "fuel_industry": fossil * shares["industry"],
        "fuel_transport": fossil * shares["transport"] + primary.get("biofuel", 0.0),
        "fuel_buildings": fossil * shares["buildings"],
    }


def cascade(components: dict[str, np.ndarray]):
    """Components (W m-2, any shape) -> (primary power P, useful work, waste heat).
    Useful work is each component times its useful fraction; waste heat is the rest, so
    work + heat = P in every cell."""
    unknown = set(components) - set(COMPONENTS)
    if unknown:
        raise KeyError(f"unknown components: {sorted(unknown)}")
    arrays = [np.asarray(v, dtype="float64") for v in components.values()]
    p = np.sum(arrays, axis=0)
    work = np.sum(
        [USEFUL_FRACTION[k] * a for k, a in zip(components, arrays, strict=True)], axis=0
    )
    return p, work, p - work


# ---- the technosphere through the year (milestone 25) -----------------------------------
#
# Monthly factors give each sector and place its typical seasonal shape; their day-weighted
# mean over a year of 365.25 days is exactly 1, so annual totals don't change and the Year
# frame equals the annual grid (as the climatology's Year frame weights months by their days).
# A day then scales the buildings' part of the month by a weather factor from the day's skin
# temperature against the 1991-2020 normal of its calendar month. Its expected value over a
# typical month is 1, so a month of ordinary weather averages to its frame.

DAYS_IN_MONTH = (31.0, 28.25, 31.0, 30.0, 31.0, 30.0, 31.0, 31.0, 30.0, 31.0, 30.0, 31.0)

HEATING_BASE_K = 288.15  # 15 C: below this daily-mean skin temperature, buildings are heated
COOLING_BASE_K = 295.15  # 22 C: above it, they are cooled
COOLING_WEIGHT = 0.5  # a degree of cooling (electric, heat pumps) per degree of heating
BASE_LOAD_K = 5.0  # weather-independent use (hot water, appliances, light), in degree-days
DAILY_SPREAD_K = 3.0  # spread of daily-mean skin temperature within a month, for the normal


def monthly_factors(monthly) -> np.ndarray:
    """(12, ...) non-negative monthly amounts -> (12, ...) factors whose mean, weighted by
    the days of each month (`DAYS_IN_MONTH`), is exactly 1. Where there is nothing all
    year, the factors are 1."""
    x = np.asarray(monthly, dtype="float64")
    if x.shape[0] != 12:
        raise ValueError(f"need 12 months on the first axis, got {x.shape}")
    days = np.asarray(DAYS_IN_MONTH).reshape((12,) + (1,) * (x.ndim - 1))
    mean = (x * days).sum(axis=0) / days.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(mean > 0, x / np.where(mean > 0, mean, 1.0), 1.0)


def heating_degrees(t_k):
    """Degrees below the heating base (K), zero above it."""
    return np.maximum(HEATING_BASE_K - np.asarray(t_k, dtype="float64"), 0.0)


def cooling_degrees(t_k):
    """Degrees above the cooling base (K), zero below it."""
    return np.maximum(np.asarray(t_k, dtype="float64") - COOLING_BASE_K, 0.0)


def _erf(x):
    """Error function, Abramowitz & Stegun 7.1.26 (|error| < 1.5e-7), vectorised."""
    s = np.sign(x)
    x = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027
                + t * 1.061405429))))  # fmt: skip
    return s * (1.0 - poly * np.exp(-x * x))


def _expected_excess(gap, spread):
    """E[max(X, 0)] for X ~ N(gap, spread^2)."""
    z = gap / spread
    pdf = np.exp(-0.5 * z * z) / np.sqrt(2 * np.pi)
    cdf = 0.5 * (1.0 + _erf(z / np.sqrt(2)))
    return spread * pdf + gap * cdf


def expected_heating_degrees(t_mean_k, spread=DAILY_SPREAD_K):
    """Mean heating degrees over a month whose daily temperatures are N(t_mean, spread^2)."""
    return _expected_excess(HEATING_BASE_K - np.asarray(t_mean_k, dtype="float64"), spread)


def expected_cooling_degrees(t_mean_k, spread=DAILY_SPREAD_K):
    """Mean cooling degrees over a month whose daily temperatures are N(t_mean, spread^2)."""
    return _expected_excess(np.asarray(t_mean_k, dtype="float64") - COOLING_BASE_K, spread)


def weather_factor(t_day_k, t_normal_k):
    """How much more (or less) energy buildings use on a day than in a typical day of its
    month: (B + HDD + c CDD) / (B + E[HDD] + c E[CDD]), with B the weather-independent base
    load, c the cooling weight and the expectations over the month's 1991-2020 normal.
    1 where either temperature is missing."""
    t_day = np.asarray(t_day_k, dtype="float64")
    t_norm = np.asarray(t_normal_k, dtype="float64")
    day = BASE_LOAD_K + heating_degrees(t_day) + COOLING_WEIGHT * cooling_degrees(t_day)
    typical = (
        BASE_LOAD_K
        + expected_heating_degrees(t_norm)
        + COOLING_WEIGHT * expected_cooling_degrees(t_norm)
    )
    with np.errstate(invalid="ignore"):
        w = day / typical
    return np.where(np.isfinite(w), w, 1.0)


def human_flows(p_base, p_bldg, w_base, w_bldg, weather):
    """A day's (P, useful work, waste heat) from its month's frame, split into the buildings'
    part (scaled by the weather factor) and the rest. W m-2."""
    p = np.asarray(p_base) + np.asarray(p_bldg) * weather
    work = np.asarray(w_base) + np.asarray(w_bldg) * weather
    return p, work, p - work
