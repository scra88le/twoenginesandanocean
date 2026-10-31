"""Zonal energy budget and global means for one frame (a date, a month or the year).

The numbers behind the zonal budget panel (Engine 2, proposal F7) and the global engine
strip (F8): zonal means, northward transport implied by the TOA budget and by `div_e`, and
Kleidon's two-box maximum-power estimate. The physics that is not new (the transport solver,
global means) is reused from `pipeline.derived`.
"""

from __future__ import annotations

import json

import numpy as np

from . import derived as d

SPLIT_LAT = 30.0  # degrees; |lat| < 30 and |lat| >= 30 are two equal-area halves
BUDYKO_A = -388.7  # W m-2
BUDYKO_B = 2.17  # W m-2 K-1

_LAT = 89.75 - 0.5 * np.arange(d.NLAT)
_TROPICS = np.abs(_LAT) < SPLIT_LAT
_EDGE_N30 = int(round((90.0 - SPLIT_LAT) / 0.5))  # edge index of 30 N (edge 0 is the pole)
_EDGE_S30 = d.NLAT - _EDGE_N30


def two_box(r_tropics: float, r_poles: float) -> dict:
    """Kleidon's two-box maximum-power estimate from the absorbed solar radiation of the two
    equal-area boxes. Linearised surface balance R - (a + b T) = +/- J with a and b from
    Budyko; the heat flux J between the boxes maximises J (T_t - T_p) / T_t, which gives
    J_opt = (R_t - R_p) / 4."""
    j_opt = (r_tropics - r_poles) / 4
    t_t = (r_tropics - BUDYKO_A - j_opt) / BUDYKO_B
    t_p = (r_poles - BUDYKO_A + j_opt) / BUDYKO_B
    g_max = (r_tropics - r_poles) ** 2 / (16 * BUDYKO_B * t_t)
    return {
        "r_tropics": r_tropics, "r_poles": r_poles, "j_opt": j_opt,
        "t_tropics": t_t, "t_poles": t_p, "delta_t": t_t - t_p, "g_max": g_max,
    }  # fmt: skip


def transport_pw(src: np.ndarray) -> np.ndarray:
    """Northward transport, PW, across the 361 cell edges (zero at both poles) that balances
    the surplus `src` (W m-2, a flux divergence or a TOA net radiation). The area-weighted
    global mean is removed first: ERA5's imbalance is not zero."""
    t = d.meridional_transport(src - d.global_mean(src))
    return np.concatenate([[0.0], t, [0.0]]) / 1e15


def _zonal(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1)


def _box_mean(x: np.ndarray, rows: np.ndarray) -> float:
    w = d._AREA_ROW[rows]
    return float((_zonal(x)[rows] * w).sum() / w.sum())


# Fields whose Year-frame global mean the overview infographic quotes (proposal F13): the layers
# `asr_sfc`, `lh`, `sh`, `precip`, the input `lw_up` and the skin temperature as `t_skin`.
OVERVIEW_MEANS = ("asr_sfc", "lw_up", "lh", "sh", "precip", "t_skin")


def zonal_summary(fields: dict[str, np.ndarray], year: bool) -> dict:
    """The panel's JSON for one frame from the frame's 0.5 degree fields `asr_toa`, `olr`,
    `skt`, `div_e` (smoothed), `j_conv`, `carnot` and `diss_bl`. The two-box estimate and the
    ocean transport only mean something for the annual mean, so only the Year frame has them
    (in other frames storage dominates the residual)."""
    asr, olr = fields["asr_toa"], fields["olr"]
    net = asr - olr
    total = transport_pw(net)
    atm = transport_pw(fields["div_e"])
    r = lambda a, n=4: [round(float(v), n) for v in a]  # noqa: E731
    out = {
        "lat": r(_LAT, 2),
        "asr_toa": r(_zonal(asr)),
        "olr": r(_zonal(olr)),
        "net_toa": r(_zonal(net)),
        "skt": r(_zonal(fields["skt"])),
        "transport_total": r(total, 5),
        "transport_atm": r(atm, 5),
    }
    g_asr, g_olr = d.global_mean(asr), d.global_mean(olr)
    g_diss = d.global_mean(fields["diss_bl"])
    out["global"] = {
        "asr_toa": round(g_asr, 4),
        "olr": round(g_olr, 4),
        "imbalance": round(g_asr - g_olr, 4),
        "j_conv": round(d.global_mean(fields["j_conv"]), 4),
        "carnot": round(d.global_mean(fields["carnot"]), 4),
        "diss_bl": round(g_diss, 4),
        "diss_bl_pct": round(100 * g_diss / g_asr, 4),
    }
    if year:
        out["transport_ocean"] = r(total - atm, 5)
        box = two_box(_box_mean(asr, _TROPICS), _box_mean(asr, ~_TROPICS))
        half_area = d._AREA_ROW.sum() * d.NLON / 2
        box["j_obs"] = (abs(total[_EDGE_N30]) + abs(total[_EDGE_S30])) * 1e15 / half_area
        box["skt_tropics"] = _box_mean(fields["skt"], _TROPICS)
        box["skt_poles"] = _box_mean(fields["skt"], ~_TROPICS)
        out["two_box"] = {k: round(float(v), 4) for k, v in box.items()}
        out["global"]["g_max_two_box"] = out["two_box"]["g_max"]
        # The overview's slots. Means of whichever of OVERVIEW_MEANS were supplied (`t_skin` is
        # `skt`); `asr_atm` is sunlight absorbed in the air; `pw_atm` and `pw_ocean` are the
        # largest poleward transports in either hemisphere (one "up to" figure each).
        given = {"t_skin": fields["skt"], **fields}
        for k in OVERVIEW_MEANS:
            if k in given:
                out["global"][k] = round(d.global_mean(given[k]), 4)
        out["global"]["t_r"] = round(float(d.radiative_temperature(g_asr)), 3)
        if "asr_sfc" in out["global"]:
            out["global"]["asr_atm"] = round(g_asr - out["global"]["asr_sfc"], 4)
        out["global"]["pw_atm"] = round(float(np.abs(atm).max()), 3)
        out["global"]["pw_ocean"] = round(float(np.abs(total - atm).max()), 3)
    return out


def budget_residual(net_toa: np.ndarray, div_e: np.ndarray, net_sfc: np.ndarray) -> dict:
    """Column energy budget residual, net_toa - div_e - net_sfc (W m-2). In the long-term mean
    the atmosphere neither gains nor loses energy, so the annual frame should close. Pass the
    unsmoothed `div_e` (`p86.162`). Reports the global mean, the global rms and the rms of the
    zonal means; ERA5 doesn't close exactly, the point is to know by how much."""
    res = net_toa - div_e - net_sfc
    zonal_rms = float(np.sqrt(d.global_mean(_zonal(res)[:, None] ** 2 * np.ones((1, d.NLON)))))
    return {
        "mean": round(d.global_mean(res), 4),
        "rms": round(float(np.sqrt(d.global_mean(res**2))), 4),
        "zonal_rms": round(zonal_rms, 4),
    }


def layer_inputs(
    layers: dict, skt: np.ndarray, lw_up: np.ndarray | None = None
) -> dict[str, np.ndarray]:
    """The `zonal_summary` inputs from a frame's layer fields, its skin temperature and, when
    it has arrived, `lw_up`. Optional layers (`OVERVIEW_MEANS`) are passed when built."""
    need = ("asr_toa", "olr", "div_e", "j_conv", "carnot", "diss_bl")
    out = {k: layers[k].values.values for k in need}
    out.update({k: layers[k].values.values for k in OVERVIEW_MEANS if k in layers})
    if lw_up is not None:
        out["lw_up"] = np.asarray(lw_up, dtype="float64")
    return {**out, "skt": np.asarray(skt, dtype="float64")}


def to_json(summary: dict) -> bytes:
    return json.dumps(summary, separators=(",", ":")).encode()
