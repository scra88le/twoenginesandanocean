# CLAUDE.md — Earth Heat Engine Map

## What this project is

A windy.com-style global map that explains the atmosphere as a heat engine, following Axel Kleidon's thermodynamic Earth-system view, and compares human energy flows with natural ones.

- **Prototype target:** global, daily, 0.5° grid, 24 layers, last 90 days.
- **Architecture:** a daily Python batch pipeline writes files to object storage. A static TypeScript front end reads them and does all rendering and point sampling in the browser.
- **No backend server.**

Audience: informed non-specialists (energy professionals, students, climate-literate readers), plus scientists checking the numbers. Every layer must be explainable and traceable to a source variable and formula.

## Working rules for Claude

- Work milestone by milestone (see **Milestones**). Finish one, run its tests, then stop and summarise before starting the next.
- **Test-first** for `pipeline.derived`, unit/sign conversions and encoding round-trips.
- All physics formulas live in **one module**, `pipeline.derived` (`pipeline/src/pipeline/derived.py`). Do not reimplement formulas in the front end. The front end only decodes and displays.
- Sign flips happen **once**, in `pipeline.convert`. Everything downstream uses the flipped, renamed fields (see **Ingestion rules**) and never negates them again.
- Never overwrite good published data. A failed run must leave yesterday's site fully working. Write `manifest.json` **last**.
- SI units throughout. Fluxes in W m⁻², temperatures in K (show °C in brackets in the UI).
- Keep layer IDs exactly as listed in **Layer catalogue**. They are used in file paths, URLs and code.
- Don't add accounts, a backend, or a JS framework unless asked. Vanilla TS + Vite is the default; Svelte is acceptable only if the UI grows.
- If a dataset ID or variable turns out to be unavailable, say so, use the documented fallback, and note it in `docs/DECISIONS.md`. Don't silently substitute.
- Credit data sources in the footer and info panels (Copernicus Climate Change Service / ECMWF for ERA5).

## Repo layout

```
/pipeline/pyproject.toml
/pipeline/src/pipeline Python package: fetch.py, load.py, convert.py, tidy.py, derived.py, layers.py, info.py, encode.py, publish.py, cli.py
/pipeline/tests        pytest
/out                   local build output (git-ignored); the data root for `npm run dev`
/web                   Vite + TypeScript front end
/web/src/layers        raster.ts, particles.ts, arrows.ts
/web/public/basemap    Natural Earth 1:50m coastlines and borders (public domain, minified)
/web/tests/fixtures    PNGs from the real encoder, for decoder tests
/web/e2e/fixtures/data a small data root (manifest + two layers) for the Playwright test
/pipeline/scripts      export_colormaps.py (writes web/src/colormap-tables.json), make_web_fixtures.py
/story                 01-fuel.md … 09-humans.md  (story-mode card text, 60–100 words each)
/docs/DECISIONS.md     log of deviations and choices made during the build
/.github/workflows/ci.yml       lint + tests for both stacks (milestone 1)
/.github/workflows/daily.yml    scheduled build and upload (milestone 13)
```

## Commands

Create these as part of milestone 1 and keep this section up to date. All commands run from the repo root unless they `cd`.

```bash
# Pipeline (local dev uses a venv at ./.venv; CI uses Python 3.12)
python3 -m venv .venv && source .venv/bin/activate   # fish: source .venv/bin/activate.fish
pip install -e "./pipeline[dev]"
pytest pipeline
ruff check pipeline
python -m pipeline.cli fetch --date YYYY-MM-DD [--wait]      # submit/collect CDS requests into ./raw
python -m pipeline.cli tidy --date YYYY-MM-DD                # raw archives -> ./work/tidy_DATE.nc
python -m pipeline.cli build --date YYYY-MM-DD --out ./out   # tidy -> layers -> PNGs + manifest
python -m pipeline.cli backfill --days 90 --out ./out
python -m pipeline.cli climatology --out ./out               # one-off, 1991–2020

# Front end
cd web && npm install
npm run dev          # serves ../out at /data/ as the data root (DATA_ROOT=... overrides)
npm run lint
npm run typecheck
npm test             # Vitest
npx playwright install chromium   # first time only
npm run e2e          # Playwright: builds, then tests the production build against e2e/fixtures/data

# Regenerate committed front-end assets (only when the encoder or colour scales change)
python pipeline/scripts/make_web_fixtures.py
pip install -e "./pipeline[tools]" && python pipeline/scripts/export_colormaps.py web/src/colormap-tables.json
```

## Tech stack

| Component | Choice |
| --- | --- |
| Pipeline | Python 3.12: `cdsapi`, `xarray`, `netCDF4`, `numpy`, `Pillow` |
| Scheduler | GitHub Actions cron, daily; CDS API key as a repo secret |
| Storage | Cloudflare R2 or AWS S3, public read |
| Front end | Vite + TypeScript |
| Map | MapLibre GL JS 6, mercator. Dark background with Natural Earth coastlines and borders drawn over the data; no tile service or API key |
| Rasters | Custom WebGL layer in MapLibre; decode packed PNGs, colour scale in a fragment shader |
| Wind | Custom WebGL particle layer (earth.nullschool / webgl-wind technique) |
| Panel charts | Observable Plot or uPlot |
| Hosting | Cloudflare Pages or GitHub Pages |
| Tests | pytest, Vitest, one Playwright smoke test |

## Data sources

| Source | Access | Used for | Latency |
| --- | --- | --- | --- |
| ERA5 daily statistics | CDS `derived-era5-single-levels-daily-statistics` | All natural single-level layers | ~6 days |
| ERA5 hourly single levels | CDS `reanalysis-era5-single-levels` | Fallback for variables missing from the daily product | ~5 days |
| ERA5 pressure-level daily statistics | CDS `derived-era5-pressure-levels-daily-statistics` (ID confirmed 2026-10-17; `daily_mean` only) | 250 hPa winds | ~6 days |
| ERA5 monthly means | CDS `reanalysis-era5-single-levels-monthly-means` | 1991–2020 monthly climatology | one-off |
| Anthropogenic heat flux | Gridded global dataset, **to be chosen** (see Open questions) | `human_q` | static |
| Our World in Data energy | CSV, CC BY | Fallback human layer: country totals spread over land area | annual |
| ENTSO-E Transparency | REST API, token | Later only: European daily wind/solar output | ~1 day |

### Ingestion rules

- Daily statistics requests: `daily_statistic: daily_mean` for state variables, `daily_sum` for accumulated variables. Use `time_zone: utc+00:00` and `frequency: 1_hourly`. A request carries one `daily_statistic`, so a date needs **three** requests: single-levels means, single-levels sums, and pressure-level means (250 hPa `u`, `v`).
- **Land-sea mask.** `g_max` and `j_ratio` are land-only, so the pipeline needs `lsm`. It is a static field, fetched in the single-levels mean request (`land_sea_mask`). A cell is land where `lsm` ≥ 0.5 after regridding. Ocean and sea-ice cells are both non-land, so no separate sea-ice field is needed.
- **Credentials.** `CDSAPI_URL` and `CDSAPI_KEY` environment variables, else `~/.cdsapirc`. Each CDS dataset's licence must be accepted once on the CDS website before the API will serve it.
- Accumulated energy (J m⁻² per day) → W m⁻²: divide by 86 400.
- `tp` (m per day) → kg m⁻² s⁻¹: × 1000 ÷ 86 400. For display in mm day⁻¹: × 1000.
- **Sign convention:** ECMWF fluxes are positive downwards. `pipeline.convert` flips the sign of `slhf`, `sshf`, `str` and `ttr` so that upward heat loss is positive, and renames the results so a flipped field can't be mistaken for a raw one:

  | Raw ERA5 | Converted field | Meaning |
  | --- | --- | --- |
  | `ttr` | `olr` = −`ttr` | Outgoing longwave at TOA |
  | `slhf` | `le` = −`slhf` | Latent heat flux, upward positive |
  | `sshf` | `h` = −`sshf` | Sensible heat flux, upward positive |
  | `str` | `lw_up` = −`str` | Net surface longwave loss, upward positive |

  All other fields keep their ERA5 short names. State the convention in each layer's info panel.
- Vertical integrals (`p…162` params) **are** in the daily product (confirmed 2026-10-17), so the hourly fallback isn't needed. Confirmed NetCDF names and GRIB parameter IDs: `vike` = 162059 (`p59.162`), `vited` = 162086 (`p86.162`), `vitee` = 162075 (`p75.162`), `viten` = 162076 (`p76.162`). The last two were used only to check the `flux_e` solver and are no longer fetched.
- **Result format.** Each CDS result is a zip holding one NetCDF per variable, whatever the file is named; each field has a length-1 `valid_time` dimension (and `pressure_level` for 250 hPa). `pipeline.load` treats the archive as untrusted, extracts it to a temporary directory, squeezes the extra dimensions and keys fields by the spec's names.
- **Regridding.** ERA5's 0.25° grid is point-centred: 1440 × 721 points, lon 0 → 359.75, lat 90 → −90 including both poles. It does not split into 2×2 blocks. Treat each ERA5 point as the centre of a 0.25° cell (pole points are half-cells), roll longitude to −180…180, and remap conservatively to the cell-centred 0.5° grid. Each 0.5° cell then overlaps a 3 × 3 stencil of ERA5 points with weights [½, 1, ½] ⊗ [½, 1, ½], multiplied by cos(lat), and normalised. Test that the global area-weighted mean is preserved. Keep native files for 30 days.
- Retry CDS requests with exponential backoff (queues can take hours). Each daily run attempts the most recent 10 days and skips dates already built.
- **Don't block on the CDS queue.** GitHub Actions kills jobs after 6 h. Submit requests without waiting, store their request IDs in `/state/pending.json` in object storage, and collect finished results on the next run.

## Layer catalogue

24 layers in 9 story groups. Inputs are ERA5 short names, or the converted names `olr`, `le`, `h` and `lw_up` for the four sign-flipped fields. **Range** is the *display* range. The *encode* range is separate and fixed (see **Encoding**). "auto" means the display range is the day's 2nd–98th percentile, symmetric about zero for diverging scales; the encode range is still fixed.

| ID | Layer | Group | Inputs | Units | Colour scale | Range |
| --- | --- | --- | --- | --- | --- | --- |
| `asr_toa` | Absorbed solar, TOA | 1 Fuel | `tsr` | W m⁻² | inferno | 0–450 |
| `asr_sfc` | Absorbed solar, surface | 1 Fuel | `ssr` | W m⁻² | inferno | 0–350 |
| `net_toa` | Net radiation, TOA | 1 Fuel | `tsr` − `olr` | W m⁻² | balance | −200 to 200 |
| `olr` | Outgoing longwave | 2 Exhaust | `olr` | W m⁻² | thermal | 100–320 |
| `t_emit` | Effective emission temperature | 2 Exhaust | derived (`olr`) | K | thermal | 200–290 |
| `carnot` | Local Carnot limit | 3 Limits | derived (`skt`, `olr`) | % | viridis | 0–30 |
| `g_max` | Maximum convective power | 3 Limits | derived (`ssr`, `skt`, `olr`) | W m⁻² | magma | 0–15 |
| `j_conv` | Actual convective heat flux | 4 Max power | `le` + `h` | W m⁻² | magma | 0–300 |
| `j_ratio` | Actual ÷ max-power flux | 4 Max power | derived | ratio | balance, centred on 1 | 0–2 |
| `lh` | Latent heat flux | 5 Surface split | `le` | W m⁻² | deep | 0–300 |
| `sh` | Sensible heat flux | 5 Surface split | `h` | W m⁻² | amp | −50 to 150 |
| `evap_frac` | Evaporative fraction | 5 Surface split | `le`, `h` | 0–1 | BrBG | 0–1 |
| `wind10` | Wind 10 m | 6 Output | `u10`, `v10` | m s⁻¹ | viridis | 0–25 |
| `wind100` | Wind 100 m | 6 Output | `u100`, `v100` | m s⁻¹ | viridis | 0–30 |
| `jet250` | Jet stream 250 hPa | 6 Output | `u`, `v` @250 hPa | m s⁻¹ | viridis | 0–80 |
| `ke_col` | Column kinetic energy | 6 Output | `p59.162` | MJ m⁻² | magma | 0–6 |
| `diss_bl` | Boundary-layer dissipation | 6 Output | `bld` | W m⁻² | magma, log | 0.01–20 |
| `tcwv` | Column water vapour | 7 Water | `tcwv` | kg m⁻² | rain | 0–70 |
| `precip` | Precipitation | 7 Water | `tp` | mm day⁻¹ | rain, log | 0.1–100 |
| `p_lift` | Power lifting water (indicative) | 7 Water | derived (`tp`) | W m⁻² | deep, log | 0.01–10 |
| `div_e` | Divergence of total energy flux (smoothed) | 8 Transport | derived (`p86.162`) | W m⁻² | balance | auto |
| `flux_e` | Divergent energy transport (arrows) | 8 Transport | derived (`div_e`) | W m⁻¹ | cividis | auto |
| `human_q` | Human energy use density | 9 Humans | anthropogenic heat dataset | W m⁻² | magma, log | 0.001–100 |
| `human_ratio` | Human ÷ natural dissipation | 9 Humans | `human_q`, `bld` | ratio | balance, log, centred on 1 | 1e-4–10 |

- Every natural layer has an anomaly variant (`{layer}_anom`). Human layers do not.
- `p_lift` must be labelled "indicative" in the UI.
- Colour scales must be perceptually uniform and colour-blind safe (matplotlib / cmocean equivalents).

## Derived quantities (implement in `pipeline.derived`)

All inputs are daily means in W m⁻² and K, taken from the converted fields, which are already sign-flipped. `derived` never negates an input.

- Constants: σ = 5.670374e-8 W m⁻² K⁻⁴, g = 9.81 m s⁻².
- Notation: OLR = `olr`, LE = `le`, H = `h`, R_s = `ssr`, T_s = `skt`.
- `evap_frac` is clipped to 0–1 for display only. Values outside that range (H < 0) are stored as computed.

| Layer | Formula | Notes |
| --- | --- | --- |
| `t_emit` | T_e = (OLR / σ)^(1/4) | |
| `carnot` | η_C = (T_s − T_e) / T_s | Clamp < 0 to 0 and render clamped cells hatched. Clamped cells are exactly 0 (the lowest valid code), which is how the front end finds them |
| `g_max` | J_opt = R_s / 2; G_max = R_s² / (4 k_r T_s); k_r = 4σT_e³ | Clip T_e to 230–290 K in k_r. Kleidon & Renner single-column model. Land only. |
| `j_ratio` | r_J = (LE + H) / J_opt | Land only; grey out ocean and sea ice (the model ignores heat storage). Also masked where R_s < 10 W m⁻², where J_opt → 0 and the ratio is meaningless |
| `evap_frac` | EF = LE / (LE + H) | Mask where LE + H < 10 W m⁻² |
| `p_lift` | P_lift = P · g · h_lift | P in kg m⁻² s⁻¹; `h_lift` is a config value, default 3000 m, shown in the info panel |
| wind speed | √(u² + v²) | Keep u, v for the particle texture |
| `human_ratio` | r_H = q_human / D_BL | Mask where `bld` < 0.01 W m⁻² |
| `div_e` | (1 − L²∇²) D_s = D, with D = `p86.162` | Implicit diffusion on the sphere: isotropic, preserves the global mean, no pole problem. L is a config value (`smooth_length_m`, default 100 km, tuned 2026-10-18) shown in the info panel. It removes grid-scale noise only; the weather-scale structure left on a given day is real (see `docs/DECISIONS.md`) |
| `flux_e` | ∇²χ = D_s − ⟨D_s⟩; F_div = ∇χ | Divergent part of the energy flux, so arrows point from sources to sinks. ⟨·⟩ is the area-weighted global mean, removed so the equation is solvable. The info panel says the circulating part is left out |

**Spherical solver for `div_e` and `flux_e`.** One finite-volume operator on the 0.5° grid (earth radius a = 6.371e6 m): FFT in longitude, then a tridiagonal solve in latitude for each zonal wavenumber. Fluxes through the pole edges are zero because cos(±90°) = 0. The same operator gives both the smoothing and the Poisson solve.

**Model background for `g_max` and `j_ratio`.** Absorbed surface solar R_s balances net longwave loss, linearised as k_r(T_s − T_a), plus the convective flux J. Convective power is J(T_s − T_a)/T_s. Maximising over J gives J_opt and G_max.

**Anomalies.**
- Raw layers: daily value minus the 1991–2020 mean for that calendar month.
- Derived layers: apply the same formula to monthly-mean inputs to get the climatology. This is an approximation because the formulas are nonlinear; say so in the info panel.

**Test fixtures (must pass):**
- OLR = 240 W m⁻² → T_e ≈ 255.1 K
- T_s = 300 K, T_e = 255 K → η_C = 15%
- R_s = 200 W m⁻², T_s = 300 K, T_e = 255 K → J_opt = 100 W m⁻², G_max ≈ 8.86 W m⁻²
- Solver: smoothing preserves the global mean and leaves a constant field unchanged; ∇·F_div reproduces D_s − ⟨D_s⟩; Gauss check: the zonal integral of northward F_div across any latitude circle equals the area integral of D_s − ⟨D_s⟩ poleward of it
- Real-data check (unsmoothed D): the zonal-mean northward F_div matches the zonal mean of raw `p76.162`, because the circulating part carries nothing across a latitude circle (**passed** 2026-10-18 on five dates, rms difference ≤ 0.02 PW; `p75.162`/`p76.162` are no longer fetched)

**Later (not MVP):** maximum-power evaporation, LE_opt = s / (s + γ) · J_opt, mapped against actual LE.

## Pipeline: daily run order

1. Read the manifest and `/state/pending.json`. List dates in the last 10 days not yet built.
2. Collect any finished CDS requests. Submit new ones for dates still missing (one CDS request per dataset per date) and record their IDs. Don't wait on the queue.
3. Convert units, flip signs, regrid to 0.5°.
4. Compute derived layers and anomalies against the stored climatology.
5. Encode and write map images, point chunks and series chunks.
6. Validate. On failure, skip that date, log it, and never overwrite good files.
7. Upload the manifest **last**.
8. Delete map images older than 90 days.

### Encoding

- Grid: 720 × 360 cells at 0.5°, cell-centred. Cell centres run lon −179.75 → 179.75 and lat 89.75 → −89.75. There are no pole rows.
- Scalar layers: uint16 packed into an RGB PNG, R = high byte, G = low byte, B = 0 (no alpha).
  - Reserved codes: **0 = no data** (missing input), **1 = masked** (land-only layer over ocean, or a threshold mask such as `evap_frac` where LE + H < 10). Valid data uses 2–65535.
  - Linear layers: value = offset + scale × (int − 2).
  - Log layers (any layer marked "log" in the catalogue): log₁₀(value) = offset + scale × (int − 2). Linear packing can't work for these; for example, linear packing of `human_q` gives a step of about 1.8e-3, larger than its 0.001 floor. Values below the floor, including zero (no rain, no human energy use), are stored as the floor and read as "< floor"; they don't count as clipped.
- Vector layers (`wind10`, `wind100`, `jet250`, `flux_e`) get **two files**: `{layer}.png`, the magnitude, packed like any scalar layer (so every raster decodes the same way and the front end never computes √(u² + v²)); and `{layer}_uv.png`, with u in R+G and v in B+A of an RGBA PNG, linear packing, same reserved codes.
- **Encode ranges and resolutions** are fixed per layer, not per day, live in one table, `pipeline.layers`, and are stored in the manifest as `lo`, `hi`, `scale` and `offset`.
  - `scale` is a fixed **resolution** per layer, about what the data and display can resolve (0.1–0.25 W m⁻² for most fluxes, 0.02 K, 0.002 decades for log layers, and so on). It is not the range divided by 65 533: a step finer than the data leaves the low byte as noise that PNG can't compress, and pushed every file past 400 kB. Each resolution must be at most 1/1000 of the display span, and the encode range must fit in 65 533 steps (tested).
  - Encode ranges are wide enough not to clip real values (based on physical limits and the 2026-10-01 data); values outside are clipped to the ends and counted. For example `lh` −200 to 1200 W m⁻², `evap_frac` −20 to 20, `carnot` 0–45% (covers the 40% validation bound), `div_e` ±2000 W m⁻², `flux_e` components ±1.5e9 W m⁻¹.
  - Anomalies (`{layer}_anom`): a linear range symmetric about zero, ±50% of the display span by default (the encode span for "auto" layers), in the layer's own units even for log layers. Resolution as the layer, or a tenth of the display floor for log layers.
- Round-trip error must be below one quantisation step, measured in log space for log layers (tested).
- **Front-end decoding:** browsers premultiply alpha and may apply colour-space conversion when they decode images, which corrupts packed data, especially v in B+A. So PNGs are **decoded in JS** (`web/src/png.ts`: `DecompressionStream` plus PNG unfiltering, 8-bit RGB/RGBA only), never through `<img>` or `createImageBitmap`. The same bytes go to the GPU as an integer texture (`RGB8UI`, read with `texelFetch`) and to the CPU for hover and readout values. The shader interpolates bilinearly after decoding, skipping no-data and masked neighbours. Vitest decodes fixture PNGs made by the real encoder, including one where every texel has A = 0.

### Storage layout

```
/manifest.json                      dates, built_layers, layers (metadata, encoding, info text), credits, build time
/fields/{YYYY-MM-DD}/{layer}.png
/fields/{YYYY-MM-DD}/{layer}_uv.png        vector layers only: u, v components
/fields/{YYYY-MM-DD}/{layer}_anom.png
/points/{YYYY-MM-DD}/{tx}_{ty}.bin  all layers, one 10°×10° tile (20×20 cells), uint16 (~19 kB)
/series/{layer}/{tx}_{ty}.bin       last 90 days, one tile, uint16 (~72 kB), rebuilt daily
/clim/{MM}/{layer}.png              monthly 1991–2020 climatology
/static/human_q.png
/logs/global_means.csv              daily validation log
/state/pending.json                 in-flight CDS request IDs (pipeline-only, not read by the front end)
```

Point and series chunks are little-endian uint16 and use the same per-layer packing and reserved codes as the PNGs.

### Validation (per date)

- Area-weighted global means:
  - `tsr` 220–260 W m⁻²
  - OLR 225–255 W m⁻²
  - `tp` 2.5–3.5 mm day⁻¹
- ≤ 1% no-data cells (code 0) in any natural layer. Masked cells (code 1) don't count.
- `carnot` within 0–40% after clamping.
- Append the global means to `/logs/global_means.csv`.

### One-off jobs

- Monthly climatology from ERA5 monthly means, 1991–2020, for every raw input. Derived climatologies are computed from those. Accumulated fields in the monthly-means product are **mean daily accumulations** (J m⁻² per day, `GRIB_stepType=avgad`; checked 2026-10-17: October 2025 `tsr` ÷ 86 400 = 245.4 W m⁻²), so the daily conversions apply unchanged.
- `human_q` from the chosen dataset, regridded to 0.5° by area-weighted averaging.

## Front end behaviour

### Layout

Full-bleed dark map with four overlays:
- layer menu (right)
- time bar (bottom)
- legend (bottom left)
- point readout panel (opens on click)

### Layer menu

- Layers grouped by the 9 story groups, each with a one-line description and an (i) info button.
- One raster active at a time.
- Overlay toggles:
  - Wind particles, with a level selector (10 m / 100 m / 250 hPa), usable over any raster.
  - Transport arrows (`flux_e`).
- An anomaly switch applies to the active raster.
- Layers listed in the manifest but not in `built_layers` are shown disabled ("Not available yet"). Radio buttons give keyboard navigation (Tab into the list, arrow keys select).

### Time bar

- Last 90 available days, newest on the right.
- Play / pause / step, plus arrow keys.
- Shows the data date and the note "ERA5, about 6 days behind real time".
- Pre-fetches ±3 days of the active layer.

### Legend

- Colour bar with units and range; log scales labelled with powers of ten.
- The value under the cursor is shown on hover.

### Point readout ("local engine")

Fetch one point chunk on click, then show:

| Line | Values |
| --- | --- |
| Fuel | absorbed surface solar |
| Hot side | T_s |
| Cold side | T_e |
| Ceiling | η_C |
| Max power | J_opt and G_max (land only) |
| Actual | LE + H and r_J |
| Split | LE, H, EF |
| Output | `bld` and 100 m wind speed |
| Water | precip and P_lift |
| Humans | `human_q` and r_H |

Below the table, a 90-day chart of the active layer at that point, with the climatology as a dashed line.

### Info panel

Source dataset and variable, units, sign convention, formula, one paragraph on its meaning for the heat engine, caveats, what grey cells mean (if the layer masks any), and the data credit.

The text lives in `pipeline/src/pipeline/info.py`, next to the formulas, and is published in the manifest. Config values the panels quote (`h_lift`, the smoothing length, the mask thresholds) are filled in from `pipeline.derived`, so they can't drift. Shown in a native `<dialog>` (Esc closes it and focus returns to the (i) button).

### Story mode

"Take the tour" runs 9 steps. Each step sets the layer, overlays and view, and shows a card loaded from `/story/NN-*.md`.

1. Fuel — `net_toa`, global
2. Exhaust — `t_emit`
3. Ceiling — `carnot`
4. The feedback — `j_ratio`, land
5. The split — `evap_frac`
6. Output — `diss_bl` + 100 m particles
7. Water — `precip` / `p_lift`
8. Transport — `div_e` + arrows
9. Humans — `human_ratio`, Europe

### URL state

The query string holds layer, anomaly flag, overlays, date, centre, zoom and pinned point. It updates on every change.

### Mobile

- Layer menu becomes a bottom sheet.
- Readout becomes a full-height sheet.
- Particle count is halved.

## Non-functional requirements

- **Performance:**
  - First map in < 3 s on 20 Mbit/s.
  - Date step < 1 s.
  - 60 fps panning with particles on a 2020-era laptop.
- **Payload:** each map PNG < 400 kB; initial load < 1.5 MB excluding basemap tiles.
- **Browsers:** latest two versions of Chrome, Firefox, Safari and Edge. WebGL2 is required; show a plain message if it's missing.
- **Accessibility:** colour-blind-safe scales; keyboard-navigable menus and panel; every value also shown as text.
- **Cost:** stays within free tiers (CDS, GitHub Actions, R2/Pages).
- **Code:** pure, unit-tested pipeline functions.

## Milestones

1. Scaffold the repo, tooling, linting, and CI running both test suites. Fill in **Commands**.
2. Fetch + convert for one fixed date. Download all inputs, apply the ingestion rules, save a tidy NetCDF. Test sign flips, unit conversions and conservative regridding. Confirm the vertical-integral and pressure-level dataset availability and the monthly-means accumulation period. (**Done.** The `div_e` and `flux_e` encode ranges moved to milestone 3, because they depend on the smoothing.)
3. Write `derived.py`, test-first, with the fixtures above, including the spherical solver for `div_e` and `flux_e`. Tune `smooth_length_m`, then set the `div_e` and `flux_e` encode ranges from a sample of dates across seasons. (**Done** 2026-10-18.)
4. Encoding + local storage layout + manifest, written to `./out`. Round-trip test (linear, log and reserved codes). Check PNG sizes against the 400 kB limit. (**Done** 2026-10-18.)
5. MapLibre basemap + WebGL raster layer from one local PNG, with legend and hover value. (**Done** 2026-10-18.)
6. Layer menu with all scalar layers and info panels. (**Done** 2026-10-18.)
7. Backfill 90 days. Time bar with play/step/pre-fetch.
8. Wind particle layer (10 m, 100 m, 250 hPa).
9. Point chunks, series chunks, readout panel, 90-day chart.
10. Climatology job + anomaly switch.
11. Human layers: `human_q` static build and `human_ratio`.
12. Story mode with the 9 Markdown cards.
13. Deploy:
    - daily GitHub Action
    - upload to object storage
    - static hosting
    - URL state
    - mobile layout
    - validation log
    - Playwright smoke test

## Acceptance criteria

- [ ] The daily job runs unattended for 7 consecutive days, with a new date each day.
- [ ] All 24 layers render for each of the last 90 days, with legend, units and info panel.
- [ ] Global-mean validation passes for every built date, and the log CSV exists.
- [ ] Derived-layer tests pass, including the three fixtures.
- [ ] Clicking any land cell shows the full readout and 90-day chart within 1 s.
- [ ] Anomaly mode works for every natural layer, on a diverging scale centred on zero.
- [ ] Wind particles animate at all three levels over any raster.
- [ ] Story mode runs through all 9 steps, forwards and back, and each step sets its layer and view.
- [ ] A copied URL restores layer, date, view and pinned point.
- [ ] A deliberately failed run (bad API key) leaves yesterday's site intact.
- [ ] Performance and payload targets are met.
- [ ] Data credits appear in the footer and info panels.

## Open questions and risks

| Item | Risk or question | Proposed handling |
| --- | --- | --- |
| Human energy data | Which gridded anthropogenic heat flux dataset, and is its licence compatible? | Shortlist published datasets (e.g. Varquez et al., 2021, *Scientific Data*). Fall back to OWID country totals. |
| `div_e` noise | Daily 0.5° `p86.162` is dominated by grid-scale noise | **Decided 2026-10-18:** smooth with implicit diffusion (see Derived quantities) |
| `flux_e` content | Raw `p75.162`/`p76.162` are dominated by circulation that carries no energy poleward | **Decided 2026-10-18:** draw only the divergent part, from smoothed `div_e` |
| KE generation | No direct ERA5 field; `bld` covers boundary-layer friction only | Later: check the definition of `p64.162`, or compute pressure-gradient work |
| Max-power model | Single-column, no storage; absolute values are illustrative | Land-only display; compare against Kleidon's published estimates; label as model-based |
| Data lag | ~6 days | State it clearly; later add ECMWF open data / GFS for same-day winds |
| CDS queue | Hours-long waits, outages; Actions jobs are killed after 6 h | Submit without waiting, track IDs in `/state/pending.json`, collect on the next run; 10-day rolling catch-up; never overwrite good data |
| Cron shutdown | GitHub disables scheduled workflows after 60 days with no repo activity | Add a keepalive step (e.g. a monthly empty commit or the API "enable workflow" call), or check it during monthly maintenance |
| Storage growth | 6.3 MB of field PNGs per date (2026-10-01), so ~570 MB for 90 days, about double with anomalies | Monitor against free tiers (R2: 10 GB) |
| Write operations | Series rebuild is 648 tiles × 24 layers ≈ 15.5k objects/day (~470k/month), plus fields and points | Within R2's free tier for writes, but monitor; skip uploading unchanged objects |
| PNG size | The low byte of a uint16 is noise when the step is finer than the data | **Resolved** with per-layer resolutions: 91–344 kB per file on 2026-10-01. Re-check on stormy winter dates |
| Basemap | Licence and attribution | **Resolved:** Natural Earth (public domain), credited in the footer. Place labels are not included yet |

Record answers to these in `docs/DECISIONS.md` as they are resolved.
