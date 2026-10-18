"""The layer catalogue: IDs, units, colour scales, display ranges and fixed encode ranges.

IDs are used in file paths, URLs and code, so they match the spec exactly. Display ranges
are the catalogue's ("auto" is None). Encode ranges are fixed, wider than the display ranges
so real values aren't clipped (uint16 leaves the steps fine), and stored in the manifest.
For log layers both ranges are in the layer's units and packing happens in log10 space.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayerSpec:
    id: str
    title: str
    group: int
    units: str
    colour: str
    display: tuple[float, float] | None  # None = "auto" (2nd-98th percentile)
    encode: tuple[float, float]
    log: bool = False
    centre: float | None = None  # diverging scales: the value at the centre colour
    uv_encode: tuple[float, float] | None = None  # vector layers: range for u and v
    anomaly: bool = True
    anomaly_encode: tuple[float, float] | None = None
    resolution: float = 0.0  # quantisation step: layer units, or log10 decades for log layers
    uv_resolution: float | None = None
    anomaly_resolution: float | None = None
    hatch_zero: bool = False  # cells clamped at exactly 0 are hatched (carnot)


GROUPS = {
    1: "Fuel",
    2: "Exhaust",
    3: "Limits",
    4: "Max power",
    5: "Surface split",
    6: "Output",
    7: "Water",
    8: "Transport",
    9: "Humans",
}

_W = "W m-2"

# Encode ranges come from physical limits and the 2026-10-01 data (see docs/DECISIONS.md).
_SPECS = [
    LayerSpec("asr_toa", "Absorbed solar, TOA", 1, _W, "inferno", (0, 450), (0, 600)),
    LayerSpec("asr_sfc", "Absorbed solar, surface", 1, _W, "inferno", (0, 350), (0, 500)),
    LayerSpec(
        "net_toa", "Net radiation, TOA", 1, _W, "balance", (-200, 200), (-400, 400), centre=0
    ),
    LayerSpec("olr", "Outgoing longwave", 2, _W, "thermal", (100, 320), (50, 400)),
    LayerSpec(
        "t_emit", "Effective emission temperature", 2, "K", "thermal", (200, 290), (150, 300)
    ),
    LayerSpec("carnot", "Local Carnot limit", 3, "%", "viridis", (0, 30), (0, 45), hatch_zero=True),
    LayerSpec("g_max", "Maximum convective power", 3, _W, "magma", (0, 15), (0, 60)),
    LayerSpec("j_conv", "Actual convective heat flux", 4, _W, "magma", (0, 300), (-300, 1500)),
    LayerSpec(
        "j_ratio", "Actual ÷ max-power flux", 4, "ratio", "balance", (0, 2), (-50, 50), centre=1
    ),
    LayerSpec("lh", "Latent heat flux", 5, _W, "deep", (0, 300), (-200, 1200)),
    LayerSpec("sh", "Sensible heat flux", 5, _W, "amp", (-50, 150), (-300, 600)),
    LayerSpec("evap_frac", "Evaporative fraction", 5, "0-1", "BrBG", (0, 1), (-20, 20)),
    LayerSpec(
        "wind10", "Wind 10 m", 6, "m s-1", "viridis", (0, 25), (0, 90), uv_encode=(-60, 60)
    ),
    LayerSpec(
        "wind100", "Wind 100 m", 6, "m s-1", "viridis", (0, 30), (0, 120), uv_encode=(-80, 80)
    ),
    LayerSpec(
        "jet250", "Jet stream 250 hPa", 6, "m s-1", "viridis", (0, 80), (0, 220),
        uv_encode=(-150, 150),
    ),  # fmt: skip
    LayerSpec("ke_col", "Column kinetic energy", 6, "MJ m-2", "magma", (0, 6), (0, 40)),
    LayerSpec(
        "diss_bl", "Boundary-layer dissipation", 6, _W, "magma", (0.01, 20), (1e-4, 1e3), log=True
    ),
    LayerSpec("tcwv", "Column water vapour", 7, "kg m-2", "rain", (0, 70), (0, 120)),
    LayerSpec(
        "precip", "Precipitation", 7, "mm day-1", "rain", (0.1, 100), (1e-3, 1e3), log=True
    ),
    LayerSpec(
        "p_lift", "Power lifting water (indicative)", 7, _W, "deep", (0.01, 10), (1e-5, 1e3),
        log=True,
    ),  # fmt: skip
    LayerSpec(
        "div_e", "Divergence of total energy flux (smoothed)", 8, _W, "balance", None,
        (-2000, 2000), centre=0,
    ),  # fmt: skip
    LayerSpec(
        "flux_e", "Divergent energy transport", 8, "W m-1", "cividis", None, (0, 2.2e9),
        uv_encode=(-1.5e9, 1.5e9),
    ),  # fmt: skip
    LayerSpec(
        "human_q", "Human energy use density", 9, _W, "magma", (0.001, 100), (1e-5, 1e4),
        log=True, anomaly=False,
    ),  # fmt: skip
    LayerSpec(
        "human_ratio", "Human ÷ natural dissipation", 9, "ratio", "balance", (1e-4, 10),
        (1e-7, 1e4), log=True, centre=1, anomaly=False,
    ),  # fmt: skip
]


# Quantisation steps: about what the data and display can resolve, so PNGs stay under
# 400 kB (measured 2026-10-18, see docs/DECISIONS.md). Log layers: decades (0.002 is 0.46%).
RESOLUTION = {
    "asr_toa": 0.25, "asr_sfc": 0.25, "net_toa": 0.25, "olr": 0.2, "t_emit": 0.02,
    "carnot": 0.02, "g_max": 0.01, "j_conv": 0.25, "j_ratio": 0.002, "lh": 0.25, "sh": 0.1,
    "evap_frac": 0.001, "wind10": 0.02, "wind100": 0.02, "jet250": 0.05, "ke_col": 0.005,
    "diss_bl": 0.002, "tcwv": 0.05, "precip": 0.002, "p_lift": 0.002, "div_e": 1.0,
    "flux_e": 1e6, "human_q": 0.002, "human_ratio": 0.002,
}  # fmt: skip
UV_RESOLUTION = {"wind10": 0.1, "wind100": 0.1, "jet250": 0.1, "flux_e": 1e6}


def _complete(s: LayerSpec) -> LayerSpec:
    """Attach resolutions and the default anomaly range (+/- half the display span, or the
    encode span for "auto"). Anomalies are linear in layer units; for log layers their
    resolution is a tenth of the display floor."""
    extra = {"resolution": RESOLUTION[s.id], "uv_resolution": UV_RESOLUTION.get(s.id)}
    if s.anomaly:
        lo, hi = s.display if s.display is not None else s.encode
        half = (hi - lo) / 2
        extra["anomaly_encode"] = (-half, half)
        extra["anomaly_resolution"] = s.display[0] / 10 if s.log else RESOLUTION[s.id]
    return LayerSpec(**{**s.__dict__, **extra})


LAYERS: dict[str, LayerSpec] = {s.id: _complete(s) for s in _SPECS}
NATURAL = tuple(i for i, s in LAYERS.items() if s.anomaly)
VECTOR = tuple(i for i, s in LAYERS.items() if s.uv_encode is not None)
