"""Info-panel text for every layer: source, formula, sign convention, meaning and caveats.

Kept next to the formulas so each layer stays traceable to its ERA5 variables, and so the
config values the panels quote (lifting height, smoothing length) come from `derived`.
Published in the manifest; the front end only displays it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .derived import H_LIFT_M, MIN_SURFACE_SOLAR, MIN_TURBULENT_FLUX, SIGMA, SMOOTH_LENGTH_M


@dataclass(frozen=True)
class LayerInfo:
    summary: str  # the one-line description in the layer menu
    source: str
    formula: str
    sign: str
    meaning: str
    caveats: str
    mask: str | None = None  # why cells are greyed out, if the layer masks any
    anomaly: str = ""  # how the anomaly is computed, or why there is none


_DAILY = "ERA5 daily statistics (Copernicus Climate Change Service / ECMWF), UTC day"
_SUM = f"{_DAILY}: daily sum of hourly accumulations, divided by 86 400 s"
_MEAN = f"{_DAILY}: daily mean of hourly values"
_UP = "Positive upward: heat leaving the surface. ECMWF stores fluxes as positive downward; the sign is flipped."
_DOWN = "Positive downward: energy absorbed."
_LAND = "Ocean and sea ice: the single-column model ignores heat storage, so it is shown over land only."
_WIND_CAVEAT = (
    "Computed from the day's mean u and v components, so it is the speed of the day's average "
    "wind. Where the direction changes during the day it is lower than the average speed."
)

_TEXT: dict[str, dict[str, str | None]] = {
    "asr_toa": dict(
        summary="Sunlight absorbed by the Earth system: the engine's fuel.",
        source=f"{_SUM}. Variable: top net solar radiation (tsr, parameter 178).",
        formula="ASR = tsr (incoming minus reflected sunlight at the top of the atmosphere)",
        sign=_DOWN,
        meaning=(
            "This is the fuel for the heat engine. On global average the Earth absorbs about "
            "240 W m⁻² of sunlight, most of it in the tropics where the sun is high. The "
            "difference between tropics and poles is what the atmosphere and oceans work to even out."
        ),
        caveats="Zero in polar night. Clouds change it a lot from day to day.",
    ),
    "asr_sfc": dict(
        summary="Sunlight absorbed at the surface, heating the ground and the ocean.",
        source=f"{_SUM}. Variable: surface net solar radiation (ssr, parameter 176).",
        formula="R_s = ssr (downward minus reflected sunlight at the surface)",
        sign=_DOWN,
        meaning=(
            "This heats the engine's hot side. It is the R_s of the maximum-power model: the "
            "energy the surface has to get rid of again, by radiation, evaporation and rising warm air."
        ),
        caveats="Depends on modelled clouds and surface reflectivity (snow, ice, desert).",
    ),
    "net_toa": dict(
        summary="Net radiation at the top of the atmosphere: where Earth gains or loses energy.",
        source=(
            f"{_SUM}. Variables: top net solar radiation (tsr, 178) and top net thermal "
            "radiation (ttr, 179)."
        ),
        formula="N = tsr − OLR, with OLR = −ttr",
        sign="Positive: the Earth system gains energy here. Negative: it loses energy.",
        meaning=(
            "The tropics take in more energy than they radiate away and the poles less. The "
            "atmosphere and oceans carry the surplus poleward, which is the engine's flow of heat "
            "from its hot side to its cold side. The global mean is close to zero."
        ),
        caveats=(
            "A single day reflects clouds and weather; the tropical surplus and polar deficit "
            "show most clearly in averages."
        ),
    ),
    "olr": dict(
        summary="Heat radiated to space: the engine's exhaust.",
        source=f"{_SUM}. Variable: top net thermal radiation (ttr, parameter 179).",
        formula="OLR = −ttr",
        sign="Positive upward: energy leaving the planet. ECMWF stores it as negative; the sign is flipped.",
        meaning=(
            "The Earth sheds the sunlight it absorbs as infrared radiation. Warm, dry, cloud-free "
            "regions emit most; the cold tops of deep thunderstorm clouds emit least."
        ),
        caveats="Daily mean; it changes with cloud cover from day to day.",
    ),
    "t_emit": dict(
        summary="The temperature at which Earth appears to radiate to space: the engine's cold side.",
        source=f"Derived from OLR. {_SUM}. Variable: ttr (parameter 179).",
        formula=f"T_e = (OLR / σ)^¼, with σ = {SIGMA} W m⁻² K⁻⁴",
        sign="Not applicable (a temperature).",
        meaning=(
            "This is the temperature of the engine's cold reservoir. Averaged over the globe it is "
            "about 255 K, about 33 K colder than the surface. That gap is the greenhouse effect, "
            "and it is the temperature range the atmospheric engine works across."
        ),
        caveats=(
            "An effective, blackbody-equivalent temperature, not the temperature of a particular "
            "layer. It mixes emission from the surface, water vapour and cloud tops."
        ),
    ),
    "carnot": dict(
        summary="The Carnot limit: the most work any engine could get from heat flowing to space.",
        source=f"Derived. {_DAILY}. Variables: skin temperature (skt, 235), ttr (179).",
        formula="η_C = (T_s − T_e) / T_s, clamped at 0. T_s is the skin temperature, T_e as in that layer.",
        sign="Not applicable (an efficiency, in %).",
        meaning=(
            "Typically 10–20%. It is a theoretical ceiling: the real atmosphere converts far less, "
            "because carrying heat away reduces the temperature difference that drives the flow "
            "(see the maximum-power layers)."
        ),
        caveats=(
            "Hatched where the surface is colder than the emission temperature and the limit is "
            "clamped at zero, as over cold ice sheets and in polar night. Assumes a reversible engine."
        ),
    ),
    "g_max": dict(
        summary="The most power convection could generate at this surface (maximum-power model).",
        source=(
            f"Derived. {_DAILY}. Variables: ssr (176), skt (235), ttr (179). "
            "Model: Kleidon & Renner (2013)."
        ),
        formula=(
            "G_max = R_s² / (4 k_r T_s), with k_r = 4 σ T_e³ (T_e clipped to 230–290 K). "
            "Reached at J_opt = R_s / 2."
        ),
        sign="Positive: power available to drive motion.",
        meaning=(
            "Rising air carries heat away from the surface, which shrinks the temperature "
            "difference that drives it. So there is an optimum heat flux, J_opt, at which the "
            "power generated peaks. Kleidon argues that convection over land runs close to this "
            "maximum."
        ),
        caveats=(
            "Single-column model without heat storage, so land only. Absolute values are "
            "illustrative and model-based."
        ),
        mask=_LAND,
    ),
    "j_conv": dict(
        summary="Heat carried up from the surface by rising air and evaporation.",
        source=(
            f"{_SUM}. Variables: surface latent heat flux (slhf, 147), surface sensible heat flux "
            "(sshf, 146)."
        ),
        formula="J = LE + H, with LE = −slhf and H = −sshf",
        sign=_UP,
        meaning=(
            "This is the engine's actual heat flow out of the surface. Compare it with J_opt, the "
            "flux at maximum power (the next layer shows the ratio)."
        ),
        caveats="Negative where the surface is colder than the air: at night, in polar regions, over sea ice.",
    ),
    "j_ratio": dict(
        summary="Actual surface heat flux ÷ maximum-power flux: is the land near maximum power?",
        source=f"Derived. {_DAILY}. Variables: slhf (147), sshf (146), ssr (176).",
        formula="r_J = (LE + H) / J_opt, with J_opt = R_s / 2",
        sign="A ratio. 1 means the surface runs exactly at maximum power.",
        meaning=(
            "Values near 1 mean the land surface sheds heat at about the rate that maximises the "
            "power of convection, as the maximum-power view predicts. Values well above or below "
            "1 point to other controls, such as dry soil or heat stored and released."
        ),
        caveats=(
            "Model-based. Daily values are affected by heat stored in soil and snow, which the "
            f"model ignores. Masked where R_s < {MIN_SURFACE_SOLAR:.0f} W m⁻², where J_opt is "
            "close to zero."
        ),
        mask=f"{_LAND} Also where there is too little sunlight (R_s < {MIN_SURFACE_SOLAR:.0f} W m⁻²).",
    ),
    "lh": dict(
        summary="Latent heat flux: energy carried up in evaporated water.",
        source=f"{_SUM}. Variable: surface latent heat flux (slhf, parameter 147).",
        formula="LE = −slhf",
        sign=_UP,
        meaning=(
            "The main way oceans and wet land shed heat. The energy is released higher up when "
            "the vapour condenses, which heats the atmosphere: water vapour is the engine's "
            "working fluid."
        ),
        caveats="Negative values mean condensation or frost forming on the surface.",
    ),
    "sh": dict(
        summary="Sensible heat flux: heat carried up by warm rising air.",
        source=f"{_SUM}. Variable: surface sensible heat flux (sshf, parameter 146).",
        formula="H = −sshf",
        sign=_UP,
        meaning="Dominates over deserts and dry land, where there is little water to evaporate.",
        caveats="Negative where the air is warmer than the surface.",
    ),
    "evap_frac": dict(
        summary="Share of the surface heat flux that goes into evaporation.",
        source=f"Derived. {_SUM}. Variables: slhf (147), sshf (146).",
        formula="EF = LE / (LE + H)",
        sign="A fraction from 0 (all sensible heat) to 1 (all evaporation).",
        meaning=(
            "Close to 1 over oceans and wet vegetation, low over deserts. It shows how much of "
            "the engine's heat flow uses water as its working fluid."
        ),
        caveats="Values outside 0–1 occur where H is negative; they are shown at the ends of the scale.",
        mask=f"Where LE + H is below {MIN_TURBULENT_FLUX:.0f} W m⁻² and the fraction is not meaningful.",
    ),
    "wind10": dict(
        summary="Wind speed 10 m above the surface.",
        source=f"{_MEAN}. Variables: 10 m u and v wind (u10, v10; parameters 165, 166).",
        formula="speed = √(u² + v²)",
        sign="Not applicable (a speed).",
        meaning=(
            "Part of the engine's mechanical output. Near the surface, friction turns this motion "
            "back into heat (see boundary-layer dissipation)."
        ),
        caveats=_WIND_CAVEAT,
    ),
    "wind100": dict(
        summary="Wind speed 100 m above the surface, about the hub height of wind turbines.",
        source=f"{_MEAN}. Variables: 100 m u and v wind (u100, v100; parameters 228246, 228247).",
        formula="speed = √(u² + v²)",
        sign="Not applicable (a speed).",
        meaning=(
            "The height where wind turbines tap the engine's output, so this is the layer to "
            "compare with human energy use."
        ),
        caveats=_WIND_CAVEAT,
    ),
    "jet250": dict(
        summary="Jet stream: wind speed at 250 hPa, about 10 km up.",
        source=(
            "ERA5 pressure-level daily statistics (Copernicus Climate Change Service / ECMWF), UTC "
            "day: daily mean. Variables: u and v wind at 250 hPa (parameters 131, 132)."
        ),
        formula="speed = √(u² + v²)",
        sign="Not applicable (a speed).",
        meaning=(
            "The fastest winds, driven by the temperature contrast between tropics and poles. "
            "Much of the atmosphere's kinetic energy sits in and around the jets."
        ),
        caveats=_WIND_CAVEAT,
    ),
    "ke_col": dict(
        summary="Kinetic energy of the air in the whole column.",
        source=f"{_MEAN}. Variable: vertical integral of kinetic energy (parameter 162059), J m⁻² ÷ 10⁶.",
        formula="KE = ∫ ½ (u² + v²) dp / g, from the surface to the top of the atmosphere",
        sign="Not applicable (always positive).",
        meaning=(
            "The engine's store of motion, about 1.5–2 MJ m⁻² on global average. It is topped up "
            "by the conversion of heat into motion and drained by friction within days."
        ),
        caveats="Daily mean of hourly values.",
    ),
    "diss_bl": dict(
        summary="Boundary-layer dissipation: wind energy turned back into heat by friction.",
        source=f"{_SUM}. Variable: boundary layer dissipation (bld, parameter 145).",
        formula="D_BL = bld",
        sign="Positive: kinetic energy converted to heat.",
        meaning=(
            "Over time, the power the engine generates equals the power lost to friction. Summed "
            "over the globe this is a few W m⁻²: about 1% of the absorbed sunlight, far below "
            "the Carnot limit."
        ),
        caveats=(
            "Boundary layer only: friction higher up and gravity-wave drag are not included. "
            "It is a model estimate, not a measured quantity."
        ),
    ),
    "tcwv": dict(
        summary="Water vapour in the whole column.",
        source=f"{_MEAN}. Variable: total column water vapour (tcwv, parameter 137).",
        formula="TCWV = ∫ q dp / g",
        sign="Not applicable (always positive).",
        meaning=(
            "Water vapour carries latent heat from where it evaporates to where it condenses. "
            "Warm air can hold more: about 7% more per kelvin."
        ),
        caveats="Daily mean of hourly values.",
    ),
    "precip": dict(
        summary="Precipitation: where water vapour condensed and released its latent heat.",
        source=f"{_DAILY}: daily sum of hourly accumulations. Variable: total precipitation (tp, parameter 228).",
        formula="P = tp × 1000 (m of water per day → mm per day)",
        sign="Not applicable (always positive).",
        meaning=(
            "Each millimetre per day of rain releases about 29 W m⁻² of latent heat into the "
            "atmosphere. Rain marks where the engine burns the fuel picked up as evaporation."
        ),
        caveats="Model precipitation, not observed. Below 0.001 mm per day it is shown as the lowest value.",
    ),
    "p_lift": dict(
        summary="Power spent lifting water that falls as rain (indicative).",
        source=f"Derived from precipitation. {_DAILY}. Variable: tp (parameter 228).",
        formula=f"P_lift = P g h_lift, with g = 9.81 m s⁻² and h_lift = {H_LIFT_M:.0f} m",
        sign="Positive: power used to lift water.",
        meaning=(
            "Lifting water vapour that later falls as rain uses part of the engine's power, "
            "estimated at around 1 W m⁻² globally. That is a large share of the engine's small output."
        ),
        caveats=(
            f"Indicative only: it assumes all rain is lifted through a fixed {H_LIFT_M:.0f} m, a "
            "round number. Real lifting heights vary widely."
        ),
    ),
    "div_e": dict(
        summary="Where the atmosphere exports (positive) or imports (negative) energy.",
        source=(
            f"{_MEAN}. Variable: vertical integral of divergence of total energy flux "
            "(parameter 162086), smoothed."
        ),
        formula=(
            f"Smoothed field D_s solves (1 − L² ∇²) D_s = D, with L = {SMOOTH_LENGTH_M / 1e3:.0f} km "
            "(diffusion on the sphere)"
        ),
        sign="Positive: the column exports energy. Negative: it imports energy.",
        meaning=(
            "On average the tropics export energy and the poles import it: the transport from "
            "the engine's hot side to its cold side."
        ),
        caveats=(
            "Daily maps are dominated by weather systems moving energy around; the tropics-to-"
            "poles pattern appears in averages. Smoothed to remove grid-scale noise."
        ),
    ),
    "flux_e": dict(
        summary="Energy transported by the atmosphere, from sources to sinks.",
        source="Derived from the smoothed divergence of total energy flux (see that layer). ERA5 parameter 162086.",
        formula="∇²χ = D_s − ⟨D_s⟩, F = ∇χ (the divergent part of the energy flux)",
        sign="The arrows point the way energy flows. The scalar map shows the size of the flux.",
        meaning=(
            "Summed across a latitude circle this matches ERA5's own energy transport: around "
            "5 PW (5 × 10¹⁵ W) poleward in mid-latitudes."
        ),
        caveats=(
            "The circulating part of the flux, which moves energy around but carries none across "
            "latitude circles, is left out."
        ),
    ),
    "human_q": dict(
        summary="Human energy use per area.",
        source="Gridded anthropogenic heat flux dataset (to be chosen, see the project's decisions log).",
        formula="q_human, the dataset's annual-mean heat release, regridded to 0.5° by area-weighted averaging",
        sign="Positive: heat released by human energy use.",
        meaning=(
            "Humanity uses about 19 TW of primary energy, about 0.04 W m⁻² over the globe, "
            "against 240 W m⁻² of absorbed sunlight. Locally, in cities, it is far higher."
        ),
        caveats="Static map, not daily. Dataset and licence still to be confirmed.",
    ),
    "human_ratio": dict(
        summary="Human energy use compared with the wind's frictional dissipation.",
        source="Derived: human energy use (see that layer) and ERA5 boundary layer dissipation (bld, 145).",
        formula="r_H = q_human / D_BL",
        sign="A ratio. 1 means human energy use equals the natural dissipation.",
        meaning="Shows where human energy flows rival the power the atmosphere's engine dissipates near the ground.",
        caveats="Human use is static and annual; dissipation is daily.",
        mask="Where boundary-layer dissipation is below 0.01 W m⁻².",
    ),
}

# How each layer's anomaly is made. The climatology is the layer's formula applied to the
# 1991-2020 ERA5 monthly means: exact for layers linear in their inputs, approximate otherwise.
_ANOM_BASE = (
    "Daily value minus the 1991–2020 mean for the same calendar month, from ERA5 monthly means "
    "(reanalysis-era5-single-levels-monthly-means)."
)
_ANOM_EXACT = f"{_ANOM_BASE} Exact: the layer is linear in its inputs, so the mean of the layer is the layer of the means."
_ANOM_APPROX = (
    f"{_ANOM_BASE} The climatology applies this layer's formula to the monthly-mean inputs. The "
    "formula is nonlinear, so that is an approximation: it differs from the mean of daily values, "
    "most where the inputs vary a lot within a month. Read small anomalies with care."
)
_ANOM_VECTOR = (
    "No anomaly. ERA5 monthly means give the speed of the month's average vector, which is far "
    "below the average of daily speeds where the direction changes (by about 1.8 m/s on average "
    "for the 10 m wind in August 2026), so the difference would show that bias, not the weather."
)
_ANOM_HUMAN = "No anomaly: this layer is not from ERA5 and has no 1991–2020 climatology."
_NONLINEAR = ("t_emit", "carnot", "g_max", "j_ratio", "evap_frac")
_VECTOR_IDS = ("wind10", "wind100", "jet250", "flux_e")
_HUMAN_IDS = ("human_q", "human_ratio")


def _anomaly_text(lid: str) -> str:
    if lid in _HUMAN_IDS:
        return _ANOM_HUMAN
    if lid in _VECTOR_IDS:
        return _ANOM_VECTOR
    return _ANOM_APPROX if lid in _NONLINEAR else _ANOM_EXACT


INFO: dict[str, LayerInfo] = {
    lid: LayerInfo(**text, anomaly=_anomaly_text(lid))  # type: ignore[arg-type]
    for lid, text in _TEXT.items()
}
