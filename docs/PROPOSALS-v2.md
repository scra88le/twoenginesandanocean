# Proposed features v2 — Earth Heat Engine Map

Specification for the next round of work on the Earth Heat Engine Map (`twoenginesandanocean`). Read it alongside `CLAUDE.md`, which stays the source of truth for everything this file does not change. Suggested location in the repo: `docs/PROPOSALS-v2.md`.

## Why

A review of the live site (2026-10-24, data date 2026-10-17) found that the engineering is strong but the site does not yet teach the heat engine. The main reasons:

1. **The title is not delivered.** The site never names the two engines or the ocean. Engine 1 is vertical: surface to atmosphere, convection, maximum power. Engine 2 is horizontal: tropics to poles, large-scale circulation. The ocean is the store and second carrier of heat. Kleidon's two-box model of Engine 2 (Kleidon 2023, *Earth Syst. Dynam.* 14, 861–896, §3.1) has no representation at all, and the ocean has none either.
2. **Daily data buries the concepts.** On one day, every concept map is dominated by weather and cloud:
   - `net_toa` shows cloud systems rather than the tropical surplus and polar deficit.
   - `div_e` shows ±500 W m⁻² storm blobs, and the arrows point every way rather than poleward.
   - `j_ratio` tests a theory meant for climatological means against single days. Kleidon states the maximum-power state is reached through a slow feedback involving heat storage.
3. **The Carnot layer contradicts its own card.** The cold side is the local daily emission temperature from OLR, so cold cloud tops dominate the map: the ITCZ and frontal bands are high, while the Sahara is low. Card 3 says the opposite. Kleidon's cold side is the radiative temperature T_r of the whole system, which he says is "not the temperature of a specific height".
4. **The headline numbers are never shown together:** a ceiling of about 12 %, against motion of about 2 W m⁻², which is under 1 % of absorbed sunlight.
5. **Smaller issues:**
   - Mercator distorts where energy is gained and lost.
   - The `rain` colour scale makes dry areas the brightest thing on a dark map.
   - The first map takes several seconds to appear, with no loading indicator.
   - Jargon (TOA, divergence, J_opt, r_J) is shown before plain words.

The fix is to make **timescale a first-class choice** (Climate · Today · Today vs normal). Then add the missing pieces: the radiative-temperature Carnot layer, an ocean layer, the zonal-mean budget chart, and a global engine strip. Finally, rebuild the tour around the three parts of the title.

## Working rules (in addition to `CLAUDE.md`)

- Same discipline as before:
  - Work milestone by milestone, test-first for `pipeline.derived`.
  - All formulas live in `pipeline/src/pipeline/derived.py`; the front end only decodes and displays.
  - Sign flips happen once, in `pipeline.convert`.
  - Write the manifest last.
- **Layer IDs stay stable.** New layers get new IDs; changed formulas keep their ID and get a `docs/DECISIONS.md` entry.
- Record every choice and deviation in `docs/DECISIONS.md`. When a milestone lands, fold the change into `CLAUDE.md` (layer catalogue, storage layout, story mode, URL state) so the spec stays current.
- **Don't re-download what you already have.** New climatology variables go in a separate set of monthly-means requests whose sums are merged by key into `work/clim/`. Do not re-fetch the existing 12 keys.
- Keep within the free tiers. Estimated new storage is roughly 200 MB (see F2, F4 and F6).

## Out of scope

- Human energy layers (`human_q`, `human_ratio`) stay skipped.
- Accounts, backend and frameworks remain out, as before.
- Same-day forecast data (ECMWF open data, GFS).

---

## F1 — Time mode: Climate · Today · Today vs normal

**What.** One three-state switch replaces the "Anomaly vs 1991–2020" checkbox:

- **Climate**: 1991–2020 monthly means, plus an annual-mean frame.
- **Today**: the daily layers as now.
- **Today vs normal**: the existing anomaly.

**Per-layer modes.** Add `modes` (the supported subset of `climate`, `today`, `anom`) and `default_mode` to `LayerSpec` in `pipeline.layers`, and publish them in the manifest.

| Layer(s) | modes | default | Notes |
|---|---|---|---|
| `net_toa`, `carnot`, `g_max`, `div_e`, `flux_e`, `net_sfc` (new, F6) | climate, today, anom* | **climate** | Concept layers: the climatology is where the idea shows |
| `j_ratio` | climate | **climate** | Daily values mislead (see Why §2); keep publishing the daily data, but don't offer it in the UI |
| `asr_toa`, `asr_sfc`, `olr`, `t_emit`, `j_conv`, `lh`, `sh`, `evap_frac`, `tcwv`, `precip`, `p_lift`, `ke_col`, `diss_bl` | climate, today, anom | today | Meaningful at both timescales |
| `wind10`, `wind100`, `jet250` | today | today | Speed rasters only; Climate mode shows mean-flow particles instead (F4) |
| `human_q`, `human_ratio` | — | — | Unchanged: "Not available yet" |

\* `flux_e` has no anomaly (vector layer); the others do.

**Behaviour.**
- If a layer doesn't support the current mode, selecting it switches the mode to the layer's `default_mode`. The legend says so in one line, e.g. "Shown as the 1991–2020 average: daily values aren't meaningful for this layer."
- Switching mode never changes the layer unless the layer doesn't support the new mode. In that case, apply the same rule as above.
- The legend always states the timescale, e.g. "1991–2020 mean, July", "Annual mean, 1991–2020", "2026-10-17" or "2026-10-17 minus the October 1991–2020 mean".

**Time bar.**
- **Today / Today vs normal:** unchanged (the last 90 days).
- **Climate:** 13 stops, Jan … Dec, then **Year**, visually separated. Play cycles Jan → Dec and loops, skipping Year, because the seasonal cycle is cyclic. Pre-fetch all 12 months of the active layer. Arrow keys step frames.

**URL state.**
- Add `mode=climate|today|anom` and `frame=01..12|year`.
- `date` is always written, so switching back to Today returns to the same day.
- Keep reading the legacy `anom=1` as `mode=anom`.
- Invalid values fall back one by one, as now.

**Readout.**
- **Climate:** the table shows the frame's values (from F2's climate point chunks). The chart becomes the 12-month cycle of the active layer at that point, with a marker on the current month. In the Year frame, mark nothing.
- **Today:** unchanged.

**Tests.** Mode resolution for every layer in the table, URL round-trip including legacy `anom=1`, time-bar stops and looping in Climate mode, legend text per mode (Vitest). Add one Playwright case: switch to Climate, play two frames, select `j_ratio` from Today, and check that the mode switches.

---

## F2 — Annual-mean frame and climate point chunks

**Annual frame.** Publish `clim/year/{layer}.png` for every climatology layer.
- **Linear layers:** the mean of the 12 monthly maps, weighted by days in month.
- **Derived layers:** apply the formula to the annual-mean inputs. Don't average the 12 derived maps. This is how the theory is formulated, so the info panel should say "computed from 1991–2020 annual-mean fluxes, as the theory intends" rather than calling it an approximation.
- **Smoothing:** `div_e` is smoothed after averaging `p86.162`.

**Climate point chunks.** Publish `clim/points/{MM|year}/{tx}_{ty}.bin`, in the same format and field order as the daily point chunks, including the extras `t_skin` and `j_opt`. This lets the readout table work in Climate mode. Size: 13 × 648 × about 21 kB ≈ 175 MB.

**Climatology series.** Extend `clim/series/{layer}` to carry the Year value as a 13th entry, or publish it separately. Pick one and record which in `docs/DECISIONS.md`.

**Manifest.** `clim` gains `frames: ["01", …, "12", "year"]` and templates for the new files.

**Tests.** The annual mean of a linear layer equals the day-weighted mean of the monthly maps. A derived annual frame uses annual-mean inputs, not the mean of derived maps. Point-chunk round-trip for one tile.

---

## F3 — Climatological transport arrows (`flux_e`)

**What.** Compute `flux_e` for each climate frame from that frame's smoothed `div_e`, using the existing solver (`derived.divergent_flux`), and publish `clim/{MM|year}/flux_e_uv.png`.

**Why this is honest.** The 2026-10-19 decision (no climatology for vector layers) still holds for wind. It does **not** apply to `flux_e`, which is linear in `div_e`. Add a `docs/DECISIONS.md` entry saying so.

**Arrow length.** In Climate mode, use one fixed reference for all 13 frames: the 98th percentile of |F| over all of them. That way arrow lengths compare across months. Today mode keeps the per-day reference.

**Acceptance.** In the Year frame, the zonal-mean northward `flux_e` is positive in the Northern Hemisphere and negative in the Southern at every latitude between 10° and 80°. Record the actual values in `docs/DECISIONS.md`.

---

## F4 — Mean-flow particles in Climate mode

**What.** In Climate mode, wind particles show the **1991–2020 mean flow** for the frame: trades, ITCZ convergence, westerlies and monsoon reversal. No speed raster is shown for the wind layers in Climate mode.

**Data.**
- Add `u10`, `v10`, `u100` and `v100` to a new set of single-level monthly-means requests.
- Add `u` and `v` at 250 hPa from `reanalysis-era5-pressure-levels-monthly-means`. Confirm the dataset ID and record it.
- Publish `clim/{MM|year}/{wind10|wind100|jet250}_uv.png` only.

**UI.**
- Legend: "Particles: mean flow at 250 hPa, 1991–2020 January".
- Particle screen speed stays proportional to the mean-vector speed. Say in the info panel that the speed of the mean wind is lower than the typical speed, and that the difference is the weather.

**Size.** About 12 MB.

---

## F5 — Carnot ceiling against the radiative temperature

**Change.** `carnot` and `g_max` use Kleidon's radiative temperature T_r of the whole system as the cold side, instead of the local emission temperature T_e.

- T_r = (⟨ASR_TOA⟩ / σ)^¼, where ⟨·⟩ is the area-weighted global mean of `tsr` **for the same frame**: the day, the month, or the year. This gives about 255 K.
- `carnot`: η_C = (T_s − T_r) / T_s. Clamp below 0 and hatch the clamped cells, as now.
- `g_max`: k_r = 4σT_r³ (the existing 230–290 K clip becomes a no-op for this T_r; keep it).
- `t_emit` is unchanged and stays a layer in its own right: it is the honest place to show cloud-top cooling.
- Publish ⟨ASR_TOA⟩ and T_r per frame in the manifest, and quote them in the info panel and the readout's "Cold side" row.

**Expected result.** The map follows surface temperature: highest over hot tropical land and deserts, about 12 % globally (T_s ≈ 288 K, T_r ≈ 255 K), and zero over polar ice. This now matches card 3. Rewrite card 2 so it no longer calls T_e "the cold side".

**Do not** use local ASR_TOA for T_r. It goes to near 0 K in polar night and sends η to 100 %.

**Tests.**
- Existing fixture: T_s = 300 K, T_r = 255 K → η_C = 15 %.
- New fixture: ⟨ASR_TOA⟩ = 240 W m⁻² → T_r ≈ 255.1 K.
- The `g_max` fixture is unchanged with T_r = 255 K → G_max ≈ 8.86 W m⁻².
- Rebuild the published 90 days and the climatology (`rebuild`), since the formula changed.

**Open question for Anthony.** Keep the current local version as an advanced layer `carnot_te`, or drop it? Default: drop it. `t_emit` already shows the cloud signal.

---

## F6 — The ocean: net surface heat flux (`net_sfc`)

**New layer** `net_sfc`, "Net heat into the surface", in a new group "Ocean".

- `net_sfc` = `ssr` − `lw_up` − `le` − `h`. Positive means energy into the surface (the ocean charging); negative means energy out (the ocean discharging).
- Units W m⁻²; `balance` colour scale; display range ±200, encode range ±600. Check both against data.
- **Mask:** none. Over land the annual mean is near zero, which is itself worth saying in the info panel.
- **Anomaly:** yes (linear).

**Data.** `str` (`surface_net_thermal_radiation`, daily sum) is in the conversion table (`str` → `lw_up`) but is **not fetched**.
- Add it to `fetch.VARIABLES` and to the new climatology request set.
- The 90 published dates lack it. Either re-fetch the sums for those dates, or show "not available yet" for older dates and let the window fill. Default: re-fetch if the CDS cost fits in two days of runs. Record the choice.

**Readout.** Add an "Ocean / storage" row: `net_sfc`, plus `lw_up` as a readout extra.

**Validation (report, don't fail).** For the Year frame, compute the column budget residual net_toa − div_e_raw − net_sfc. It should be small, because in the long-term mean the atmosphere neither gains nor loses energy. Use the unsmoothed `p86.162`. Record the global and zonal rms in `docs/DECISIONS.md`. ERA5 doesn't close exactly; the point is to know by how much.

---

## F7 — Zonal energy budget panel (Engine 2)

A small chart panel, opened by a "Zonal budget" button in the menu and by tour steps that set `panel: zonal`. It is the site's picture of Engine 2, after Kleidon (2023) Fig. 8.

**Data.** For every daily date and every climate frame, publish one JSON file: `zonal/{YYYY-MM-DD}.json` and `clim/zonal/{MM|year}.json`. Each contains:

- **`lat`:** 360 cell-centre latitudes.
- **Zonal means:** `asr_toa`, `olr` and `net_toa` (W m⁻²), and `skt` (K).
- **`transport_total`:** northward transport implied by the TOA budget, in PW, at the 361 cell edges. Remove the area-weighted global mean of `net_toa` first, so the transport is zero at both poles (ERA5's TOA imbalance is not zero). Reuse `derived.meridional_transport`.
- **`transport_atm`:** the same from `div_e`, with its global mean removed. This should equal the zonal integral of northward `flux_e` (Gauss check, already tested).
- **`transport_ocean`:** `transport_total − transport_atm`. **Year frame only.** In other frames, storage dominates the residual; label it "ocean + storage" or omit it. Default: omit.
- **`two_box`:** Kleidon's two-box maximum-power estimate.
  - Split at ±30° into two equal-area halves.
  - R_s,t and R_s,p: area means of `asr_toa` for |φ| < 30° and |φ| ≥ 30°.
  - Budyko parameters: a = −388.7 W m⁻², b = 2.17 W m⁻² K⁻¹.
  - J_opt = (R_s,t − R_s,p) / 4.
  - T_s,t = (R_s,t − a − J_opt) / b and T_s,p = (R_s,p − a + J_opt) / b.
  - G_max = (R_s,t − R_s,p)² / (16 b T_s,t).
  - Also report the diagnosed J_obs: total transport across 30° N and 30° S, summed as magnitudes and divided by half the Earth's area. Report the observed box-mean `skt` too.
  - Show the two-box numbers for the Year frame only, with a note that the model is for the annual mean.
- **`global`:** the inputs to F8.

**Chart.**
- Top: zonal `asr_toa` (red) and `olr` (blue) against latitude, with surplus and deficit shaded.
- Bottom: northward transport, total plus atmosphere (plus ocean in the Year frame).
- Use an x-axis linear in sin φ, so the area under each curve is honest.
- Below the chart, a one-line two-box comparison: "Max-power prediction: J ≈ 32 W m⁻², ΔT ≈ 30 K. ERA5: J = …, ΔT = …".
- Use uPlot, as the readout chart does.

**Tests (pipeline).**
- Two-box fixture from Kleidon (2023): R_s,t = 306 and R_s,p = 177 W m⁻² give J_opt = 32.25 W m⁻², T_s,t ≈ 305.3 K, T_s,p ≈ 275.6 K, ΔT ≈ 29.7 K and G_max ≈ 1.57 W m⁻².
- Transport is zero at both poles after removing the mean.
- `transport_atm` at the edges matches the zonal integral of `flux_e`.

---

## F8 — Global engine strip

A slim, always-visible strip above the time bar (it collapses on phones). It shows the frame's area-weighted global means, plain label first and symbol second:

| Item | Source |
|---|---|
| Sunlight absorbed | ⟨`asr_toa`⟩ |
| Heat radiated to space | ⟨`olr`⟩ |
| Imbalance | difference of the above |
| Heat lifted by convection | ⟨`j_conv`⟩ |
| Ceiling (Carnot) | ⟨`carnot`⟩ % |
| Max power, two-box (Year frame only) | `two_box.G_max` |
| Motion lost to friction near the ground | ⟨`diss_bl`⟩, and as % of absorbed sunlight |

Values come from the F7 JSON (`global`). Each item has a tooltip with its formula and links to the layer's (i) panel. This is where "12 % ceiling, under 1 % achieved" becomes visible.

---

## F9 — Tour rewrite: two engines and an ocean

**Front matter.** Extend the card front matter with:
- `mode: climate|today|anom` (default `today`, for backwards compatibility)
- `frame: 01..12|year` (required when `mode: climate`)
- `panel: zonal|none` (default `none`)

`particles: jet250` with `mode: climate` means mean-flow particles (F4). Update `story.ts`, its tests and the "exactly what it lists" rule: a step also sets the mode, the frame and the panel.

**Cards.** Replace the nine cards with twelve, grouped in three chapters plus an opening and a close. The progress dots show the chapter breaks. Each body must stay within the existing 60–100-word test. The drafts below are a starting point: check the word counts and the numbers.

| # | File | Title | layer | mode / frame | Overlays | View (lng, lat, zoom) |
|---|---|---|---|---|---|---|
| 1 | `01-engine.md` | Two engines and an ocean | `net_toa` | climate / year | — | 10, 15, 1.4 |
| 2 | `02-fuel.md` | Engine one: fuel | `asr_sfc` | climate / year | — | 10, 15, 1.4 |
| 3 | `03-ceiling.md` | The ceiling | `carnot` | climate / year | — | 10, 15, 1.4 |
| 4 | `04-limit.md` | Working at the limit | `j_ratio` | climate / year | — | 15, 20, 2.2 |
| 5 | `05-split.md` | The split | `evap_frac` | climate / year | — | 10, 15, 1.4 |
| 6 | `06-surplus.md` | Engine two: surplus and deficit | `net_toa` | climate / year | panel: zonal | 10, 15, 1.4 |
| 7 | `07-transport.md` | Transport | `div_e` | climate / year | arrows | −30, 35, 1.5 |
| 8 | `08-output.md` | Output | `ke_col` | climate / 01 | particles: jet250 | −30, 40, 1.6 |
| 9 | `09-battery.md` | The ocean battery | `net_sfc` | climate / 07 | — | 10, 15, 1.4 |
| 10 | `10-ocean-share.md` | The ocean's share | `net_sfc` | climate / year | panel: zonal | −40, 35, 1.6 |
| 11 | `11-today.md` | The engine today | `ke_col` | today | particles: wind100 | 10, 15, 1.4 |
| 12 | `12-explore.md` | Explore | `net_toa` | climate / year | — | 10, 15, 1.4 |

**Draft bodies.**

1. **Two engines and an ocean.** Earth is a heat engine. Averaged over a year, the tropics absorb more sunlight than they radiate away (red), and higher latitudes radiate more than they absorb (blue). The crossover lies around 35–40° latitude. Carrying heat from the surplus to the deficit takes work. Two engines do it: a vertical one that lifts heat off the surface, and a horizontal one that moves it towards the poles. The ocean stores heat and carries part of the load. This map is the 1991–2020 average.

2. **Engine one: fuel.** Engine one starts at the ground. Most of the sunlight the planet absorbs is taken up at the surface: about **160 W m⁻²** on average, far more in the tropics and almost none in polar winter. The surface has to get rid of that heat. Some leaves as infrared radiation. The rest is carried up by rising air and evaporating water. That second route is convection, and convection is a heat engine: it turns part of the heat it carries into motion.

3. **The ceiling.** No engine can turn all of its heat into work. The ceiling, the Carnot limit, depends only on the hot and cold sides: **η = (T_s − T_r) / T_s**. The hot side is the surface. The cold side is Earth's radiative temperature, about **255 K (−18 °C)**: the coldest temperature at which the planet can shed the sunlight it absorbs. The ceiling is highest over hot tropical land and falls to zero over polar ice. Averaged over the globe it is about 12 %.

4. **Working at the limit.** Convection undermines itself. The more heat it lifts, the more it cools the surface and warms the air, shrinking the temperature difference that drives it. Kleidon and Renner showed that power peaks when the flux carries about **half the sunlight absorbed at the surface**. This map divides the real flux of evaporation plus sensible heat by that optimum. Values near 1 suggest the land works close to its limit. The theory is meant for long-term averages like this one, not single days.

5. **The split.** The engine has two exhaust routes. **Latent heat** leaves as water vapour, **sensible heat** as warm air. The evaporative fraction, LE / (LE + H), says which dominates: near 1 over oceans and rainforests, near 0 over deserts. The split matters because vapour releases its heat only where it condenses, often far away and high in the atmosphere. Evaporation therefore links engine one to engine two, and makes water the working fluid of the whole system.

6. **Engine two: surplus and deficit.** Engine two runs between the tropics and the poles. The chart averages the map around each latitude. Absorbed sunlight (red) peaks at the equator, while outgoing infrared (blue) is much flatter, because heat is carried away from where it arrives. Kleidon's two-box model splits Earth at 30° and finds the transport that gives the most power: about **32 W m⁻²** over each half of the planet, close to the roughly 43 W m⁻² observed. The panel repeats the calculation for ERA5.

7. **Transport.** Averaged over a year, the atmosphere exports energy from the tropics (red) and imports it at high latitudes (blue). The arrows show the part of the flux that runs from sources to sinks, and they point overwhelmingly poleward. Air and ocean together carry about **5–6 petawatts** across 35° latitude, several hundred times humanity's energy use. Switch to Today and this map fills with storms: on a single day, weather systems store and release far more energy than this steady flow.

8. **Output.** The engine's product is motion. This is the kinetic energy of the whole air column in January, with the mean flow at 250 hPa, about 10 km up. The jet streams are strongest in the winter hemisphere, where the equator-to-pole temperature difference is largest: a bigger difference gives the engine more to work with. Step to July and the northern jets weaken. Globally, generating this motion takes about **2 W m⁻²**, under 1 % of the sunlight absorbed.

9. **The ocean battery.** The ocean is the system's storage. This map shows the net heat flowing into the surface in July. The summer-hemisphere ocean absorbs heat (red) while the winter-hemisphere ocean gives it back (blue). Because water holds so much heat, the ocean smooths the seasons and keeps the winter engine running on summer sunlight. Step through the months to watch the charge move north and south with the Sun. Over land the flow nearly balances across the year.

10. **The ocean's share.** Averaged over a year, the tropical ocean absorbs heat, and the ocean gives it up far to the north. The release is strongest along the Gulf Stream and the Kuroshio, where losses exceed 100 W m⁻². In between, currents carry the heat poleward. The chart now splits the total transport between atmosphere and ocean: the ocean carries the larger share in the deep tropics, the atmosphere in mid-latitudes.

11. **The engine today.** Everything so far has been the average engine. This is the engine running on the date in the time bar: today's column kinetic energy and winds at 100 m. Day to day, the engine is a weather map. Storms build and release energy far faster than the steady flows behind them, which is why the concepts need long averages to show. Switch to **Today vs normal** to see how this day differs from the 1991–2020 average for its month.

12. **Explore.** That is the whole engine: sunlight in, heat out, a ceiling set by temperature, convection working near its limit, transport by air and sea, and motion as the product. Use the switch to move between **Climate**, **Today** and **Today vs normal**. In Climate, the time bar steps through the months; in Today, through the last 90 days. **Click any point** for its local engine. Each layer's (i) button gives its source and formula. Human energy use is not mapped yet.

**Check before publishing.** Verify each number in the drafts against the published data or the cited source. Change the wording rather than the data if they disagree: the 160 W m⁻² surface solar, the 35–40° crossover, the 5–6 PW peak transport, the ocean and atmosphere shares, and the Gulf Stream losses.

---

## F10 — Menu regrouping

Regroup the layers under the title's structure. `GROUPS` in `pipeline.layers` changes; layer IDs don't. Mark technical layers `advanced: true` and collapse them under "More layers" in each group by default.

| Group | Layers (advanced in *italics*) |
|---|---|
| Engine one: surface to sky | `asr_sfc`, `carnot`, `g_max`, `j_ratio`, `evap_frac`, *`j_conv`*, *`lh`*, *`sh`* |
| Engine two: tropics to poles | `net_toa`, `div_e`, `flux_e`, `ke_col`, `jet250`, *`asr_toa`*, *`olr`*, *`t_emit`*, *`diss_bl`*, *`wind10`*, *`wind100`* |
| The ocean | `net_sfc` |
| Water | `precip`, `tcwv`, *`p_lift`* |
| Humans | `human_q`, `human_ratio` (not available yet) |

Each group header gets a one-line explanation. One-line layer descriptions put the plain-language name first.

At the top of the menu, beside "Take the tour", add a **How the engine works** button that opens the overview infographic (F13).

---

## F11 — Readability fixes

1. **Colour scales on the dark theme.** Sequential scales that start near white (`rain`, `deep`, `amp`) make low values the brightest thing on the map. Use reversed variants, so that low is dark and high is bright, or a scale that starts dark. Regenerate `colormap-tables.json` (`export_colormaps.py`) and update the colour-map tests. Check that `precip`, `tcwv`, `lh`, `p_lift` and `sh` all read correctly against the dark basemap.
2. **Loading state.** Show a visible "Loading map…" indicator from first paint until the first raster draws. In the 2026-10-24 review, the map was blank for several seconds with no feedback. Re-measure first-map time from the deployed bucket, as the existing acceptance criterion notes it hasn't been timed there.
3. **Plain labels first.** In the readout, legend and info panels, put the plain words first and the symbol second, e.g. "Heat lifted by convection (LE + H)" and "Share of the optimum (r_J)". Keep symbols for the scientists checking the numbers.
4. **Readout energy-flow diagram.** Above the readout table, add a small inline SVG of the column:
   - sunlight absorbed at the surface (`asr_sfc`) going in;
   - LE, H and net longwave (`lw_up`, from F6) going up;
   - the remainder into or out of the surface (`net_sfc`).
   Draw it to scale by width, with values as text for accessibility. It depends on F6.

---

## F12 — Globe projection (spike, optional)

Mercator roughly doubles the visual area of high latitudes at the default zoom, which distorts where energy is gained and lost. MapLibre supports a globe projection.

The spike should find out:
1. what the custom WebGL layers (`raster.ts`, `particles.ts`, `arrows.ts`, `mat4.ts`) need in order to render under globe;
2. the performance cost with particles on;
3. whether hover and click sampling still map correctly.

Record the findings in `docs/DECISIONS.md` and recommend: globe by default, a toggle, or stay on Mercator. Don't ship the change without a decision.

---

## F13 — "How the engine works" overview infographic

**What.** A single stylised infographic that gives the conceptual overview before anyone looks at a map. It shows a cross-section of the planet from tropics to pole and surface to space, with the key flows drawn as arrows. Each part is labelled with the layers that show it in detail. It answers "what am I looking at?" in one screen, and it is the map of the site itself: every element leads to the layer or tour step that shows it.

- **First visit:** opens automatically over the map.
- **Any time later:** opened from the menu with a "How the engine works" button, next to "Take the tour".

**Composition.** A stylised, hand-authored inline SVG, not a cartographic view. Left is the tropics (surplus) and right is the high latitudes (deficit). From bottom to top: ocean, surface, atmosphere, space. Rough layout guide, not a design:

```
   ☀ Sunlight absorbed ≈ {asr_toa}                       Heat radiated to space ≈ {olr} ↑↑↑
 ┌──────────────────────────────── ATMOSPHERE ─────────────────────────────────────┐
 │ absorbed in air ≈ {asr_atm}    ENGINE TWO: tropics ═══ heat carried ═══▶ poles   │
 │       ▲ heat released where vapour condenses (rain ≈ {precip})  air ≈ {pw_atm}   │
 │       │                                    motion ≈ {diss_bl} ↺ friction → heat  │
 │ ENGINE ONE: convection lifts ≈ {j_conv}  (latent {lh} · sensible {sh})           │
 │   ceiling ≈ {carnot} · optimum ≈ half the sunlight at the surface                │
 ├── SURFACE: hot side T_s ≈ {t_skin} ──────────────── cold side T_r ≈ {t_r} ───────┤
 │ sunlight at surface ≈ {asr_sfc}   infrared lost ≈ {lw_up}                        │
 │ OCEAN: stores summer heat · carries ≈ {pw_ocean} poleward · releases it in winter │
 │        and along western boundary currents                                        │
 └───────────────────────────────────────────────────────────────────────────────────┘
      TROPICS (surplus)                                          HIGH LATITUDES (deficit)
```

**Visual language.**
- **Colours** match the layers: solar in warm yellows, infrared in thermal reds, latent heat and water in blue-greens, the ocean in deep blue, and motion as white streaks like the wind particles.
- **Arrow widths** are proportional to the flux within each unit family:
  - the W m⁻² fluxes share one scale;
  - poleward transport in PW gets its own;
  - a small key says so.
  Stylised, but honest about which flows are big.
- **The two engines** are drawn as engine glyphs (simple hot-side/cold-side symbols) placed where each operates. The ocean is drawn as a battery or store.
- **Animation:** optional and gentle (dashes moving along the flows). Off under `prefers-reduced-motion`.

**Numbers.**
- Every `{slot}` is filled from the 1991–2020 **annual-mean** frame, because this is the conceptual, long-term engine, never a single day.
- Values come from `clim/zonal/year.json` (F7). Extend its `global` block to carry the area-weighted global mean of every scalar layer, plus `lw_up`, `t_skin`, T_r and ⟨`asr_toa`⟩ − ⟨`asr_sfc`⟩ (`asr_atm`).
- `pw_atm` and `pw_ocean` are the peak magnitudes of `transport_atm` and `transport_ocean` in each hemisphere. Show both hemispheres, or one rounded "up to" value: choose one and record it in `docs/DECISIONS.md`.
- Round for reading (≈ 240 W m⁻², ≈ 12 %) and give exact values in tooltips.
- Footnote: "ERA5, 1991–2020 annual mean".
- If the climatology isn't published, render without numbers. Never hard-code values in the SVG.

**Interaction.**
- **Three highlight chips** across the top: **Engine one · Engine two · The ocean · All**. A chip highlights that part's flows and labels and dims the rest, with two or three sentences of plain explanation beside it. Default: All.
- **Clickable elements.** Each labelled element is a focusable control. Clicking one closes the overview and **opens the tour at the matching step**, reusing that card's front matter to set the layer, mode, frame, overlays and view. State handling is therefore shared with the tour (F9), not duplicated.

  | Element | Value slot(s) | Opens tour step |
  |---|---|---|
  | Sunlight absorbed / heat to space / surplus and deficit | `asr_toa`, `olr` | 01 (`net_toa`) |
  | Sunlight at the surface | `asr_sfc` | 02 (`asr_sfc`) |
  | Engine one: ceiling (hot and cold sides) | `carnot`, `t_skin`, `t_r` | 03 (`carnot`) |
  | Engine one: convection and the optimum | `j_conv` | 04 (`j_ratio`) |
  | Latent and sensible split, the water loop | `lh`, `sh`, `precip` | 05 (`evap_frac`) |
  | Engine two: tropics to poles | zonal surplus and deficit | 06 (`net_toa` + zonal panel) |
  | Heat carried poleward by air | `pw_atm` | 07 (`div_e` + arrows) |
  | Motion and friction | `diss_bl` | 08 (`ke_col` + mean flow) |
  | The ocean as store | — | 09 (`net_sfc`, July) |
  | Heat carried poleward by the ocean | `pw_ocean` | 10 (`net_sfc` + zonal panel) |

  A unit test checks that every element maps to an existing card, and that every layer named on the infographic exists in the manifest.
- **Footer buttons:** **Take the tour** (primary, opens step 1), **Explore the map** (closes), and a close button (×).

**First-visit behaviour.**
- Show the overview automatically when the visitor hasn't seen it before. Remember dismissal in `localStorage` (`ehe.overview.seen = 1`), wrapping every read and write in try/catch. If storage is unavailable, show it once per page load and don't retry.
- Don't auto-show when the URL has `?tour=N` (the tour takes over) or `?overview=0`. `?overview=1` always opens it, which is useful for links and tests.
- The map and first raster keep loading behind the overlay. Showing the overview first also hides the current first-load delay (F11 §2).
- Deep links with layer, date or pin still get the overview on a first visit. Closing it reveals the linked state unchanged.

**Menu entry.** Add a "How the engine works" button at the top of the layer menu, beside "Take the tour" (see F10). On phones, put it in the bottom sheet's header.

**Layout and accessibility.**
- **Container:** a native `<dialog>`. Focus moves into it; Esc closes it and returns focus to whatever opened it (the menu button, or the map on first visit).
- **Size:** desktop takes up to about 90 % of the viewport, with the SVG scaled to fit. Under 700 px it's a full-screen sheet with a **vertical layout variant**: space, atmosphere, surface and ocean stacked, with the tropics-to-pole axis drawn as a narrow band. Both layouts are authored as separate SVGs that share the same element IDs and value slots.
- **SVG semantics:** `<title>` and `<desc>` on the SVG and on each element. Each clickable element has an accessible name that includes its value, e.g. "Heat carried poleward by the ocean, up to 2 petawatts: open tour step 10".
- **Text alternative:** a "Read as text" toggle replaces the graphic with an ordered list of the same elements, values and links.
- **Contrast:** colours meet WCAG AA against the dark background. Highlighting never relies on colour alone; dimming plus outline is fine.

**Implementation notes.**
- New module `web/src/overview.ts`, with the SVGs as files in `web/src/overview/`, bundled at build time like the story cards.
- Value slots are marked `data-slot="asr_toa"` etc. Highlight groups are marked `data-part="engine1|engine2|ocean"`. Tour links are marked `data-step="07"`.
- Vanilla TypeScript, no new dependencies.
- Text in the SVG is real `<text>`, not outlined paths, so it can be translated and read by assistive technology.
- Insert values with `textContent`, never as HTML.

**Tests.**
- **Vitest:**
  - every `data-slot` is filled from a fixture `year.json`, and none is left empty when the climatology exists;
  - slots render "—" when it doesn't;
  - every `data-step` points to an existing card;
  - every `data-part` is one of the three parts;
  - first-visit logic: not seen → shown; seen → not shown; storage throws → shown once; `?tour`, `?overview=0` and `?overview=1` behave as specified.
- **Playwright:**
  - a fresh context shows the overview;
  - "Explore the map" closes it, and a reload doesn't show it again;
  - the menu button reopens it;
  - clicking the ocean-transport element opens tour step 10 with `net_sfc` in Climate/Year and the zonal panel open;
  - Esc returns focus.
- Run on the desktop and phone viewports.

---

## F14 — The ocean overlay: the Atlantic overturning (AMOC)

**New overlay**, not a map layer: the two limbs of the Atlantic Meridional Overturning Circulation as coloured particles, usable over any raster in Today and Today vs normal.

- **Data.** Copernicus Marine Service, Global Ocean Physics Analysis and Forecast (GLO12, `GLOBAL_ANALYSISFORECAST_PHY_001_024`), dataset `cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m`: daily-mean `uo`, `vo` on 50 depth levels at 1/12°. It assimilates satellite sea level and SST, sea ice and Argo profiles; satellites see only the surface, so the deep limb has to come from the model. Free account; credentials `COPERNICUSMARINE_SERVICE_USERNAME` and `_PASSWORD`; `copernicusmarine` toolbox (optional dependency group `ocean`).
- **Subset.** The Atlantic box 100°W–25°E, 40°S–80°N, all depths, one day per request (about 0.5 GB).
- **Limbs.** Upper 0–1100 m (warm, northward), deep 1100 m to the sea floor (cold, southward); 1100 m is where the overturning at 26.5°N reverses (RAPID). For each: U = ∫u dz, V = ∫v dz (m² s⁻¹) and the water thickness H, in `pipeline.derived` (`limb_transports`, read one level at a time).
- **Encoding.** Conservative average to the 0.5° grid (land counts as no flow), Atlantic only (`ocean.basin_mask`: cells with ≥ 30 % ocean connected to the open North Atlantic, east of the Central American divide). Per limb: `{limb}.png`, the transport |(U, V)| (log, 0.01–10⁵ m² s⁻¹), which sets particle **density**; `{limb}_uv.png`, the depth-mean velocity (U, V) / H (m s⁻¹), which sets particle **speed and direction**. Masked where the limb holds less than 50 m (upper) or 200 m (deep) of water.
- **Averaging.** The day, and the 30-day mean ending on it (mean U, V, H; velocity = mean U / mean H), published once 24 of the 30 days are in. The front end falls back to the daily field and says so.
- **26.5°N diagnostics**, at full resolution, Florida to Africa (81°W–13°W): the overturning streamfunction ψ(z) and its maximum (the AMOC strength, Sv) and depth, and each limb's net northward transport. Shown in the legend; comparable with RAPID's ~17 Sv.
- **Storage.** `ocean/{date}/{limb}{_30d}{_uv}.png` (outside `fields/`, so an ERA5 rebuild can't delete it); `state/ocean/{date}.npz`, the daily 0.5° integrals, kept for the window; manifest `ocean` block (limbs, file templates, per-date window count and 26.5°N figures, info text, credit). ERA5 manifest writes carry the block forward.
- **Schedule.** A second job in `daily.yml`, after the ERA5 build and never alongside it (both write the manifest). At most 15 downloads a run: missing published dates first, newest first, then their windows. Skipped with a notice while the secrets are unset.
- **Front end.** One particle layer per limb (orange upper, blue deep), the wind particle layer with two options: a colour, and a weight field (a respawning particle is kept with probability transport / `density_ref`, else parked off the map until the next frame). Menu: "Ocean overturning" toggle, limbs (both, upper, deep), averaging (30-day mean, daily), (i). Legend line with swatches, the period and the 26.5°N figures; hover gives each limb's transport, speed and direction. URL `ocean=both|upper|deep`, `ocean_avg=daily`. Off in Climate mode (no 1991–2020 normal) and in tour steps.

## Milestones

Continue the numbering from `CLAUDE.md`. Stop and summarise after each, as before.

14. **Pipeline foundations.**
    - Fetch `str` daily (F6) and choose a backfill route.
    - New climatology request set for `str` and the winds (F4, F6), merged by key.
    - Implement `net_sfc` (F6) and the T_r change to `carnot` and `g_max` (F5), test-first.
    - Build the annual frame (F2).
    - Run `rebuild`.
15. **Climate data products.**
    - Climate point chunks (F2).
    - Climatological `flux_e` (F3) and mean-flow uv files (F4).
    - Zonal JSON with the two-box estimate and global means, for dates and frames (F7, F8), with the Kleidon fixture.
    - Column-budget residual report (F6).
16. **Mode switch** (F1): manifest `modes` and `default_mode`, the switch, the Climate time bar, URL state, the readout in Climate mode, legend timescale text.
17. **Climate overlays:** Climate-mode arrows with a fixed reference (F3), and mean-flow particles (F4).
18. **Engine 2 and the global strip:** the zonal budget panel (F7) and the global engine strip (F8).
19. **Story and menu:** the twelve-card tour and front-matter extensions (F9), and the regrouped menu with advanced layers (F10).
20. **Overview infographic** (F13): desktop and phone SVGs, value slots from `clim/zonal/year.json`, highlight chips, links into tour steps, first-visit logic, menu entry, text alternative. This comes after milestone 19 because its links reuse the new tour cards.
21. **Readability:** colour scales, loading state, plain labels, readout energy-flow diagram (F11).
22. **Globe spike (optional):** findings and recommendation only (F12).
23. **Ocean overlay** (F14): the AMOC formulas in `pipeline.derived` (test-first), `pipeline.ocean`, the `ocean` CLI command and daily job, the coloured and density-weighted particle layer, controls, legend, URL state, fixtures and tests.

## Acceptance criteria

- [ ] Every layer opens in its `default_mode`. Selecting a layer in an unsupported mode switches mode, with a legend note. Copied URLs restore the mode and frame, and legacy `anom=1` still works.
- [ ] Climate mode plays Jan → Dec in a loop. The Year frame exists for every climatology layer.
- [ ] Clicking any cell in Climate mode shows the full readout and a 12-month chart within 1 s.
- [ ] In the Year frame:
  - `net_toa` changes sign between 30° and 45° latitude in both hemispheres;
  - Climate arrows point poleward at every latitude between 10° and 80°;
  - `transport_total` is zero at both poles.
- [ ] The `carnot` map is highest over hot low-latitude land and lowest or zero over polar ice in the Year frame, matching card 3. The global mean is between 10 and 14 %.
- [ ] The two-box fixture passes. The Year-frame panel shows the prediction next to the ERA5 diagnosis.
- [ ] `net_sfc` exists for the daily dates (or follows the documented backfill choice) and for all climate frames. The column-budget residual is recorded.
- [ ] The global engine strip shows all seven items for every frame and date. Each value traces to a formula in `pipeline.derived`.
- [ ] The tour runs all 12 steps forwards and back, and each step sets the layer, mode, frame, overlays, panel and view. Every card passes the 60–100-word test.
- [ ] A first visit shows the overview infographic and a return visit doesn't. The menu reopens it on desktop and phone. Every element opens its tour step with the right map state. Every value is filled from the annual-mean climatology, and the text alternative lists the same content.
- [ ] Low values are dark on every sequential layer. A loading indicator shows until the first raster draws.
- [ ] Payload and performance targets from `CLAUDE.md` still hold with the strip and panel loaded.
- [ ] The ocean overlay shows both limbs over the Atlantic for every published date with its 30-day mean, the deep limb flowing south along the American slope, and a 26.5°N AMOC strength within a few Sv of RAPID's (F14).
- [ ] `CLAUDE.md` and `docs/DECISIONS.md` are updated for every change above.

## Open questions

| Item | Question | Default if not answered |
|---|---|---|
| `carnot_te` | Keep the current local-T_e Carnot as an advanced layer? | Drop it; `t_emit` shows the cloud signal |
| `str` backfill | Re-fetch 90 days of sums, or let the window fill? | Re-fetch if it fits in two daily runs |
| Default mode on first visit | Open the site in Climate (Year) or Today? | Climate, Year frame, `net_toa`; the tour starts there too |
| Ocean residual in monthly frames | Show "ocean + storage" or hide it? | Hide it |
| Globe | Ship globe after the spike? | Decide from the spike's findings |
| Overview transport values | Show peak PW for each hemisphere, or one rounded "up to" figure? | One rounded figure each for air and ocean |
| Overview animation | Animate the flows by default? | Yes, gently; off under reduced motion |
