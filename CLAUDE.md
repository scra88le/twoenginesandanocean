# CLAUDE.md — Earth Heat Engine Map

## What this project is

A windy.com-style global map that explains the atmosphere as a heat engine, following Axel Kleidon's thermodynamic Earth-system view, and compares human energy flows with natural ones.

- **Prototype target:** global, daily, 0.5° grid, 24 layers, last 90 days at the start, growing to 365 (2026-10-31: `publish.KEEP_DAYS`; no backfill, one new date a day).
- **Architecture:** a daily Python batch pipeline writes files to object storage. A static TypeScript front end reads them and does all rendering and point sampling in the browser.
- **No backend server.**

Audience: informed non-specialists (energy professionals, students, climate-literate readers), plus scientists checking the numbers. Every layer must be explainable and traceable to a source variable and formula.

## Working rules for Claude

- Current work: docs/PROPOSALS-v2.md, milestones 14–22. Where it conflicts with this file, the proposal wins
- Work milestone by milestone (see **Milestones**). Finish one, run its tests, then stop and summarise before starting the next.
- **Test-first** for `pipeline.derived`, unit/sign conversions and encoding round-trips.
- All physics formulas live in **one module**, `pipeline.derived` (`pipeline/src/pipeline/derived.py`). Do not reimplement formulas in the front end. The front end only decodes and displays.
- Sign flips happen **once**, in `pipeline.convert`. Everything downstream uses the flipped, renamed fields (see **Ingestion rules**) and never negates them again.
- Never overwrite good published data. A failed run must leave yesterday's site fully working. Write `manifest.json` **last**.
- SI units throughout. Fluxes in W m⁻², temperatures in K (show °C in brackets in the UI).
- Keep layer IDs exactly as listed in **Layer catalogue** (titles may change; they say the plain words first, then the symbol after a comma). They are used in file paths, URLs and code.
- Don't add accounts, a backend, or a JS framework unless asked. Vanilla TS + Vite is the default; Svelte is acceptable only if the UI grows.
- If a dataset ID or variable turns out to be unavailable, say so, use the documented fallback, and note it in `docs/DECISIONS.md`. Don't silently substitute.
- Credit data sources in the footer and info panels (Copernicus Climate Change Service / ECMWF for ERA5).

## Repo layout

```
/pipeline/pyproject.toml
/pipeline/src/pipeline Python package: fetch.py, load.py, convert.py, tidy.py, derived.py, layers.py, info.py, encode.py, points.py, climatology.py, publish.py, validate.py, run.py, store.py, deploy.py, daily.py, ocean.py, cli.py
/pipeline/tests        pytest
/out                   local build output (git-ignored); the data root for `npm run dev`
/web                   Vite + TypeScript front end
/web/src/overview      desktop.svg, the overview infographic (read by overview.ts)
/web/src/layers        raster.ts, particles.ts (wind, and the ocean limbs: colour + density weight), arrows.ts
/web/public/basemap    Natural Earth 1:50m coastlines and borders (public domain, minified)
/web/tests/fixtures    PNGs from the real encoder, for decoder tests
/web/e2e/fixtures/data a small data root (manifest, three rasters, uniform 10 m and 250 hPa winds, zonal JSON for the 13 frames and two dates, 15 built layers with Climate views for the tour's) for the Playwright tests
/pipeline/scripts      export_colormaps.py (writes web/src/colormap-tables.json), make_web_fixtures.py
/story                 01-fuel.md … 09-explore.md  (story-mode cards: front matter for the step's layer, overlays and view, then 60–100 words of text)
/docs/DECISIONS.md     log of deviations and choices made during the build
/.github/workflows/ci.yml       lint + tests for both stacks
/.github/workflows/daily.yml    scheduled build, validate and upload; keep-alive; smoke test
/.github/workflows/site.yml     build the front end and publish it to GitHub Pages; smoke test
/docs/DEPLOY.md                 setting up the bucket, secrets and workflows; running it day to day
/README.md                      what this is and where things are
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
python -m pipeline.cli backfill --days 90 --out ./out [--wait]  # fetch, build, validate and publish the last 90 days
python -m pipeline.cli rebuild --out ./out                   # re-run every published date from ./work tidy files, then series
python -m pipeline.cli series --out ./out                    # rebuild the series chunks from the published PNGs
python -m pipeline.cli climatology --out ./out [--wait]      # one-off: fetch ERA5 monthly means 1991–2020, publish clim/, refresh the manifest
python -m pipeline.cli rebuild --out ./out                   # afterwards: adds {layer}_anom.png to the published dates
python -m pipeline.cli upload --store s3://BUCKET --out ./out        # publish a data root (manifest last); file:///dir works too
python -m pipeline.cli daily --store s3://BUCKET [--days 10]         # the daily job: collect/submit, build, validate, publish
pip install -e "./pipeline[ocean]"                                   # the ocean overlay needs the copernicusmarine toolbox
python -m pipeline.cli ocean [--store s3://BUCKET] [--max-fetch 15]  # AMOC overlay for the published dates (Copernicus Marine GLO12)

# Front end
cd web && npm install
npm run dev          # serves ../out at /data/ as the data root (DATA_ROOT=... overrides)
npm run lint
npm run typecheck
npm test             # Vitest
npx playwright install chromium   # first time only
npm run e2e          # Playwright: builds, then tests the production build (also under /earth/) against e2e/fixtures/data
SITE_URL=https://... npm run smoke   # Playwright smoke test of a deployed site (see docs/DEPLOY.md)

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
| ERA5 monthly means | CDS `reanalysis-era5-single-levels-monthly-means`, `reanalysis-era5-pressure-levels-monthly-means` (250 hPa winds) | 1991–2020 monthly climatology | one-off |
| Anthropogenic heat flux | Gridded global dataset, **to be chosen** (see Open questions) | `human_q` | static |
| Our World in Data energy | CSV, CC BY | Fallback human layer: country totals spread over land area | annual |
| ENTSO-E Transparency | REST API, token | Later only: European daily wind/solar output | ~1 day |
| Copernicus Marine GLO12 | `copernicusmarine` toolbox, free account (`COPERNICUSMARINE_SERVICE_USERNAME`/`_PASSWORD`); `GLOBAL_ANALYSISFORECAST_PHY_001_024`, dataset `cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m` | The ocean overlay: daily-mean `uo`, `vo`, 50 levels, 1/12°, Atlantic box | ~1 day |

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
- **Request by month.** Runs of consecutive missing dates within one month go in one request per statistic (cost = variables × days, at most 9 × 31 against the CDS limit of 400), and the result is split into per-date archives `{name}_{date}.nc`. A 90-day backfill is about 12 requests instead of 270.
- **Queue limit.** The CDS rejects requests beyond a small, undocumented number queued per dataset per user. Keep at most 2 queued per dataset (`fetch.MAX_QUEUED`), submit the oldest dates first across all three statistics, and resubmit rejected or failed requests on a later poll.
- **Raw pruning.** A per-date raw archive is deleted after 30 days only once its date has a tidy file, so a date that is still waiting for its other archives is never re-fetched. Tidy files are kept for 90 days.
- **Don't block on the CDS queue.** GitHub Actions kills jobs after 6 h. Submit requests without waiting, store their request IDs in `/state/pending.json` in object storage, and collect finished results on the next run.

## Layer catalogue

25 layers in 5 groups (Engine one: surface to sky; Engine two: tropics to poles; The ocean; Water; Humans). Technical layers are `advanced` and sit under "More layers" in the menu (`pipeline.layers.ADVANCED`; menu order `MENU`). Inputs are ERA5 short names, or the converted names `olr`, `le`, `h` and `lw_up` for the four sign-flipped fields. **Range** is the *display* range. The *encode* range is separate and fixed (see **Encoding**). "auto" means the display range is the day's 2nd–98th percentile, symmetric about zero for diverging scales; the encode range is still fixed.

| ID | Layer | Group | Inputs | Units | Colour scale | Range |
| --- | --- | --- | --- | --- | --- | --- |
| `asr_toa` | Sunlight absorbed, top of atmosphere | 2 Engine two | `tsr` | W m⁻² | inferno | 0–450 |
| `asr_sfc` | Sunlight absorbed, surface | 1 Engine one | `ssr` | W m⁻² | inferno | 0–350 |
| `net_toa` | Net radiation, top of atmosphere | 2 Engine two | `tsr` − `olr` | W m⁻² | balance | −200 to 200 |
| `olr` | Heat radiated to space, OLR | 2 Engine two | `olr` | W m⁻² | thermal | 100–320 |
| `t_emit` | Temperature seen from space, T_e | 2 Engine two | derived (`olr`) | K | thermal | 200–290 |
| `carnot` | Efficiency ceiling, Carnot limit | 1 Engine one | derived (`skt`, `tsr`) | % | viridis | 0–30 |
| `g_max` | Maximum convective power | 1 Engine one | derived (`ssr`, `skt`, `tsr`) | W m⁻² | magma | 0–15 |
| `j_conv` | Heat lifted by convection, LE + H | 1 Engine one | `le` + `h` | W m⁻² | magma | 0–300 |
| `j_ratio` | Share of the optimum, r_J | 1 Engine one | derived | ratio | balance, centred on 1 | 0–2 |
| `lh` | Latent heat flux | 1 Engine one | `le` | W m⁻² | deep | 0–300 |
| `sh` | Sensible heat flux | 1 Engine one | `h` | W m⁻² | amp | −50 to 150 |
| `evap_frac` | Evaporative fraction | 1 Engine one | `le`, `h` | 0–1 | BrBG | 0–1 |
| `wind10` | Wind 10 m | 2 Engine two | `u10`, `v10` | m s⁻¹ | viridis | 0–25 |
| `wind100` | Wind 100 m | 2 Engine two | `u100`, `v100` | m s⁻¹ | viridis | 0–30 |
| `jet250` | Jet stream 250 hPa | 2 Engine two | `u`, `v` @250 hPa | m s⁻¹ | viridis | 0–80 |
| `ke_col` | Column kinetic energy | 2 Engine two | `p59.162` | MJ m⁻² | magma | 0–6 |
| `diss_bl` | Friction near the ground, BL dissipation | 2 Engine two | `bld` | W m⁻² | magma, log | 0.01–20 |
| `tcwv` | Column water vapour | 4 Water | `tcwv` | kg m⁻² | rain | 0–70 |
| `precip` | Precipitation | 4 Water | `tp` | mm day⁻¹ | rain, log | 0.1–100 |
| `p_lift` | Power lifting water (indicative) | 4 Water | derived (`tp`) | W m⁻² | deep, log | 0.01–10 |
| `div_e` | Heat exported by the air, energy flux divergence (smoothed) | 2 Engine two | derived (`p86.162`) | W m⁻² | balance | auto |
| `flux_e` | Divergent energy transport (arrows) | 2 Engine two | derived (`div_e`) | W m⁻¹ | cividis | auto |
| `human_q` | Human energy use density | 5 Humans | anthropogenic heat dataset | W m⁻² | magma, log | 0.001–100 |
| `human_ratio` | Human ÷ natural dissipation | 5 Humans | `human_q`, `bld` | ratio | balance, log, centred on 1 | 1e-4–10 |
| `net_sfc` | Net heat into the surface | 3 Ocean | `ssr` − `lw_up` − `le` − `h` | W m⁻² | balance | −200 to 200 |

- Every natural layer has an anomaly variant (`{layer}_anom`; `net_sfc` once the `str` climatology is in), **except the four vector layers** (`wind10`, `wind100`, `jet250`, `flux_e`): monthly means only give the speed of the mean vector, far below the mean of daily speeds (+1.8 m/s bias at 10 m, August 2026), so there is no honest climatology for them (decided 2026-10-19). Human layers have none either. That leaves 19 layers with anomalies (`pipeline.layers.ANOMALY`).
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
| `carnot` | η_C = (T_s − T_r) / T_s; T_r = (⟨ASR_TOA⟩ / σ)^¼ | 1 Engine one
| `g_max` | J_opt = R_s / 2; G_max = R_s² / (4 k_r T_s); k_r = 4σT_r³ | 1 Engine one
| `j_ratio` | r_J = (LE + H) / J_opt | 1 Engine one
| `net_sfc` | Q = R_s − lw_up − LE − H | 3 Ocean
| `evap_frac` | EF = LE / (LE + H) | 1 Engine one
| `p_lift` | P_lift = P · g · h_lift | 4 Water
| wind speed | √(u² + v²) | Keep u, v for the particle texture |
| `human_ratio` | r_H = q_human / D_BL | 5 Humans
| `div_e` | (1 − L²∇²) D_s = D, with D = `p86.162` | 2 Engine two
| `flux_e` | ∇²χ = D_s − ⟨D_s⟩; F_div = ∇χ | 2 Engine two
| ocean limbs | U = ∫u dz, V = ∫v dz over 0–1100 m and 1100 m–floor; H = water thickness; velocity (U, V) / H | ocean overlay (not a layer)
| AMOC at 26.5° N | ψ(z) = ∫∫ v dx dz from the surface to z; strength = max ψ | ocean overlay, in Sv

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

`pipeline.cli daily` (`pipeline.daily.run_daily`), on a runner that is gone afterwards, so everything it needs comes from the object store:

1. Check the CDS credentials (`check_authentication`: collection metadata is public, so a bad key would otherwise only fail at the first request, and not at all on a day with nothing to request), then ask which date is newest. A failure here changes nothing.
2. Download the state: `manifest.json`, `logs/global_means.csv`, `state/pending.json`, the climatology maps (`clim/clim.json`, `clim/MM/*.png`) and the scalar maps of the published dates (the series are rebuilt from them): about 425 MB in 1 957 files.
3. One backfill pass over the last 10 dates, never waiting on the queue: collect finished requests, submit missing ones (one request per dataset per date, at most two queued per dataset) and build every date whose three archives are all there. A request stays in the state until its dates are published, because the downloaded archives vanish with the runner (`fetch_dates(keep_collected=True)`, `settle_state`); a result CDS has expired is forgotten and requested again.
4. Per date: convert units, flip signs, regrid; derive the layers; anomalies against the climatology; encode maps, point chunks and anomaly maps; **validate**. A date that fails is skipped, logged and not published, and the run fails at the end; other dates still publish. Then rebuild the series.
5. Upload (`pipeline.deploy.upload`): maps, points and climatology, then the series, then the log, then the **manifest last**; unchanged objects (same size and MD5) are skipped; only after the manifest are the files of dates beyond the 90-day window deleted. Then save `state/pending.json`.
6. A failure before step 5's manifest leaves the published site exactly as it was. If the run crashes after submitting requests, their IDs are still saved.

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
  - Anomalies (`{layer}_anom`): a linear range symmetric about zero, ±50% of the display span by default (the encode span for "auto" layers), in the layer's own units even for log layers. Resolution as the layer, or the display floor for log layers (a tenth of it made `diss_bl_anom` 404 kB). Value = daily value − the 1991–2020 mean for the date's calendar month; masked where either is masked.
  - Anomaly display: a fixed symmetric range per layer (`ANOMALY_DISPLAY`, set from the anomalies of the published dates), on `balance`, or `BrBG` for the water layers (`lh`, `evap_frac`, `tcwv`, `precip`, `p_lift`).
- Round-trip error must be below one quantisation step, measured in log space for log layers (tested).
- **Front-end decoding:** browsers premultiply alpha and may apply colour-space conversion when they decode images, which corrupts packed data, especially v in B+A. So PNGs are **decoded in JS** (`web/src/png.ts`: `DecompressionStream` plus PNG unfiltering, 8-bit RGB/RGBA only), never through `<img>` or `createImageBitmap`. The same bytes go to the GPU as an integer texture (`RGB8UI`, read with `texelFetch`) and to the CPU for hover and readout values. The shader interpolates bilinearly after decoding, skipping no-data and masked neighbours. Vitest decodes fixture PNGs made by the real encoder, including one where every texel has A = 0.

### Storage layout

```
/manifest.json                      dates, built_layers, layers (metadata, encoding, info text), radiative (⟨ASR⟩ and T_r per date), credits, build time, ocean (the ocean overlay's limbs, files, dates with their 26.5° N figures; written by `pipeline.ocean`, carried forward by every other manifest write)
/fields/{YYYY-MM-DD}/{layer}.png
/fields/{YYYY-MM-DD}/{layer}_uv.png        vector layers only: u, v components
/fields/{YYYY-MM-DD}/{layer}_anom.png
/points/{YYYY-MM-DD}/{tx}_{ty}.bin  all 24 layers + readout extras, one 10°×10° tile (20×20 cells), uint16 (20.8 kB)
/series/{layer}/{tx}_{ty}.bin       the published dates (up to 90), one tile, uint16 (~72 kB), rebuilt daily
/clim/{MM}/{layer}.png              monthly 1991–2020 climatology, the layer's own packing
/clim/year/{layer}.png              annual-mean frame: formulas applied to the day-weighted annual-mean inputs, not the mean of 12 derived maps
/clim/year/series/{layer}/{tx}_{ty}.bin  the annual value of one tile (400 codes); apart from clim/series so those keep 12 months
/clim/series/{layer}/{tx}_{ty}.bin  the 12 monthly means of one tile (12 × 20 × 20 codes, month-major), for the readout chart
/clim/points/{MM|year}/{tx}_{ty}.bin  the daily point-chunk layout for one frame; wind layers are no-data (speed of a mean wind is not a mean speed)
/clim/{MM|year}/{flux_e|wind10|wind100|jet250}_uv.png  vectors only: divergent energy flux and 1991–2020 mean flow
/clim/zonal/{MM|year}.json          zonal means, transport (PW), global means; Year adds two_box, transport_ocean, budget_residual
/zonal/{YYYY-MM-DD}.json            the same for a daily date (no two_box or ocean)
/clim/clim.json                     period, layers and file templates; copied into the manifest's `clim` (null until published)
/ocean/{YYYY-MM-DD}/{limb}.png            ocean overlay: transport |(U, V)| of `amoc_upper` / `amoc_deep` (log); sets particle density
/ocean/{YYYY-MM-DD}/{limb}_uv.png         depth-mean velocity (U, V) / H, m/s; moves the particles
/ocean/{YYYY-MM-DD}/{limb}_30d[_uv].png   the same for the 30-day mean ending on the date (once 24 of 30 days are in)
/ocean/{YYYY-MM-DD}/{limb}_30d_ov[_uv].png   the mean's overturning part: each limb's transport minus H_limb × the whole column's mean velocity (`derived.overturning_part`), so the depth-uniform gyre flow is gone and the limbs cancel
/ocean/{YYYY-MM-DD}/section[_30d].json    the Atlantic's overturning streamfunction on a latitude-depth section: `{"psi": [level][lat], "upper_sv": [lat], "deep_sv": [lat]}`: ψ in tenths of a Sv at each level's bottom edge, and the two limbs' net northward transport per latitude in Sv (`derived.limb_transports_by_latitude`: ψ at 1,100 m, and the rest of the column), null where the basin has no water; grid in the manifest's `ocean.section_grid` (40° S–80° N in 0.5° bins, the model's depth edges)
/state/ocean/{YYYY-MM-DD}.npz             the day's 0.5° limb integrals, 26.5° N figures and latitude-depth ψ (pipeline-only), kept for the window; a save without ψ is fetched again
/static/human_q.png
/logs/global_means.csv              daily validation log
/state/pending.json                 in-flight CDS request IDs (pipeline-only, not read by the front end)
```

Point and series chunks are little-endian uint16 and use the same per-layer packing and reserved codes as the PNGs (`pipeline.points`).

- Tiles: 36 × 18; tile (tx, ty) covers grid columns 20·tx … 20·tx + 19 and rows 20·ty … 20·ty + 19 (row 0 is the north). Within a tile, cells are row-major.
- Point chunk: the fields in the manifest's `points.fields` order (the 24 layers, then the extras `t_skin` = T_s and `j_opt` = J_opt, which the readout needs but which aren't map layers), field-major. Layers not built yet are code 0. Extras are computed in `pipeline.derived` and their encodings are in the manifest's `points.extras`.
- Series chunk: `EHS1`, uint32 n, n uint32 dates as YYYYMMDD, then n × 400 codes, date-major. The dates are in the file because published dates can have gaps, and so a series file is self-consistent whatever the manifest says at that moment. Each file is replaced atomically.
- Series are rebuilt from the published PNGs after each backfill pass that published something, after `build`, and by `rebuild` / `series`.

### Validation (per date)

- Area-weighted global means:
  - `tsr` 220–260 W m⁻²
  - OLR 225–255 W m⁻²
  - `tp` 2.5–3.5 mm day⁻¹
- ≤ 1% no-data cells (code 0) in any natural layer. Masked cells (code 1) don't count.
- `carnot` within 0–40% after clamping.
- Append the global means to `/logs/global_means.csv` (columns `date, tsr, olr, tp_mm_day, status, problems`; one row per date, rewritten when a date is rebuilt). Implemented in `pipeline.validate`; a date that fails is logged and not published.

### One-off jobs

- Monthly climatology from ERA5 monthly means (`reanalysis-era5-single-levels-monthly-means`), 1991–2020, for every raw input of the anomaly layers (`pipeline.climatology`). Since 2026-10-24 a second set of requests, merged by key (`climatology.Part`: `SURFACE` = `str` and the 10/100 m winds, `PRESSURE` = 250 hPa `u`, `v` from `reanalysis-era5-pressure-levels-monthly-means`), adds `lw_up` and the winds without re-fetching the first 12 keys; `climatology --partial` publishes from the parts that have arrived. Six requests of five years × 12 inputs (cost 2 880 each, limit 20 000; ~1 GB each), at most two queued. Each is reduced on arrival to per-calendar-month sums on the 0.5° grid through the same conversion as the daily data (`work/clim/sums_*.nc`, ~220 MB) and the download deleted. Accumulated fields are stamped 06:00 on the 1st, others 00:00, so fields are matched by month. Derived climatologies apply the layer formulas to the monthly means. Accumulated fields in the monthly-means product are **mean daily accumulations** (J m⁻² per day, `GRIB_stepType=avgad`; checked 2026-10-17: October 2025 `tsr` ÷ 86 400 = 245.4 W m⁻²), so the daily conversions apply unchanged.
- `human_q` from the chosen dataset, regridded to 0.5° by area-weighted averaging.

## Front end behaviour

### Layout

Full-bleed dark map with six overlays:
- layer menu (right)
- time bar (bottom)
- legend (bottom left)
- point readout panel (opens on click)
- global engine strip (above the time bar; see **Global engine strip**)
- zonal budget panel (opens from the menu; see **Zonal budget panel**)

### Layer menu

- Layers in the 5 groups of the catalogue, each group with a one-line explanation (manifest `groups`), each layer with a one-line description (plain name first) and an (i) info button. `advanced` layers are collapsed under "More layers" in each group; the group opens by itself when the active layer is one of them.
- One raster active at a time.
- Overlay toggles:
  - Wind particles, with a level selector (10 m / 100 m / 250 hPa), usable over any raster.
  - Transport arrows (`flux_e`): see **Transport arrows** below.
- A **timescale switch** (Climate · Today · Today vs normal, at the top of the menu) applies to the active raster. Each layer's manifest `modes` and `default_mode` say what it offers; a layer opens in its default mode, selecting a layer keeps the mode unless the layer can't show it (then its default is used and the legend says so), and switching mode never changes the layer. Climate and Today vs normal are disabled for a layer without a published climatology; the legacy `?anom=1` reads as `mode=anom`. The legend states the timescale ("1991–2020 mean, July", "Annual mean, 1991–2020", "2026-10-17", "2026-10-17 minus the October 1991–2020 mean"). Each layer's info panel has an "Anomaly" section: exact for layers linear in their inputs, an approximation for `t_emit`, `carnot`, `g_max`, `j_ratio` and `evap_frac`, and why there is none for the others.
- Layers listed in the manifest but not in `built_layers` are shown disabled ("Not available yet"). Radio buttons give keyboard navigation (Tab into the list, arrow keys select).

### Wind particles

- Custom WebGL layer (`web/src/layers/particles.ts`). Particle state lives on the GPU and is advanced with transform feedback, sampling the `{layer}_uv.png` field with `texelFetch` and bilinear interpolation after decoding (same decode as the raster). Each step is drawn as a line into a fading offscreen trail texture, which is redrawn at its old map position when the view moves, so trails stay attached to the ground while panning.
- In Climate mode they show the 1991–2020 **mean flow** of the frame (`clim/{frame}/{level}_uv.png`): legend "Particles: mean flow at 250 hPa, 1991–2020 January", hover "Mean wind 10 m: …". Speed stays on the daily colour scale, so the mean flow moves slower than a day's wind.
- On by default at 10 m; the menu's Overlays section switches them off or picks 10 m / 100 m / 250 hPa (unbuilt levels are disabled). `?particles=off|wind10|wind100|jet250` sets the start state until full URL state lands.
- Screen speed is proportional to wind speed and the same at every zoom and latitude (the top of the level's colour range moves at 180 px/s), so it reads as speed rather than the map's stretching.
- One particle per 90 px² of map (at most 32 768), halved under 700 px. Particles that leave the view, reach the end of their life (up to 4 s) or land on a cell with no data respawn at random in the view.
- The legend says what they show ("Particles: wind at 10 m (daily mean)"), and hovering shows the wind under the cursor as text, e.g. "Wind 10 m: 7.3 m/s from SW". A date without that level's wind says so instead.
- `?debug` exposes `window.ehe = { map, particles }`; `particles.readState()` returns the particle state, which the Playwright tests use to check that particles move downwind.

### Time bar

- Climate mode: 12 months (slider) and a separate Year button, ← → step the frames, Play loops January to December and skips Year, all 13 frames of the active layer are pre-fetched. The rest of this section is Today / Today vs normal.
- The available days (90 on 2026-10-31, growing by one a day to 365), newest on the right.
- Play / pause / step, plus arrow keys.
- Shows the data date and the note "ERA5, about 6 days behind real time".
- Pre-fetches ±3 days of the active layer, and of the particle level's u, v field when particles are on.
- Steps through the manifest's dates, so a date that failed or isn't built yet is skipped. Arrow keys step the date when nothing else has focus (or a time-bar button does); elsewhere they keep their usual job. Play advances every 800 ms, waits for each date to draw, starts again from the oldest date if it's at the newest, and stops at the newest.

### Legend

- Until the first raster draws, a "Loading map…" indicator (`#loading`, in the static HTML so it shows from first paint; `body[data-drawn]` is set when it goes).

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

- Above the table, an energy-flow diagram of the surface column (`energyflow.ts`): sunlight absorbed in, latent heat, sensible heat and infrared out, the net heat into (or out of) the surface. Arrow widths share one scale and every value is also text (the SVG's accessible name). It is hidden when `asr_sfc`, `lh`, `sh` or `net_sfc` is unbuilt or has no value at the cell (for instance Climate frames without them).
- Opens on a click on the map (or `?pin=lng,lat` until URL state lands), at the clicked cell's centre, with a marker. The close button or Esc closes it. Under 700 px it is a full-height sheet.
- T_s and J_opt come from the point chunk's extras; everything else is a layer. Masked values show "—" with the mask reason as a tooltip and accessible label; unbuilt layers say "not available yet".
- The table follows the date; the chart follows the active layer and marks the date. The chart has one point per day with gaps where a date has no value or isn't published, and a log axis for log layers (uPlot). The dashed climatology line is each calendar month's 1991–2020 mean at that cell, from `clim/series`; layers without a climatology say so.

### Info panel

Source dataset and variable, units, sign convention, formula, one paragraph on its meaning for the heat engine, caveats, what grey cells mean (if the layer masks any), and the data credit.

The text lives in `pipeline/src/pipeline/info.py`, next to the formulas, and is published in the manifest. Config values the panels quote (`h_lift`, the smoothing length, the mask thresholds) are filled in from `pipeline.derived`, so they can't drift. Shown in a native `<dialog>` (Esc closes it and focus returns to the (i) button).

### Zonal budget panel

- A "Zonal budget" toggle under "Take the tour" opens `#zonal` beside the readout (desktop only); × or Esc closes it and returns focus to the toggle. `?panel=zonal` opens it at load and is written while it is open.
- Data: `clim/zonal/{frame}.json` in Climate mode (`clim.zonal` template), `zonal/{date}.json` in Today and Today vs normal (`web/src/zonal.ts`, which checks the shape and caches hits). A file that is missing (daily files exist only for dates built after milestone 15) gives a message in the panel and dashes in the strip, not an error.
- Two uPlot charts (`web/src/zonalpanel.ts`) with an x-axis linear in sin φ and ticks at 60°S, 30°S, 0, 30°N, 60°N: zonal `asr_toa` (red) and `olr` (blue) with surplus and deficit shaded, and northward transport (total, atmosphere, and ocean in the Year frame only). A legend, a "The numbers as text" fold-out (surplus band, peak transport) and a source note come with them.
- One line below the charts: "Max-power prediction: J ≈ 31 W m⁻², ΔT ≈ 29 K. ERA5: J = 41 W m⁻², ΔT = 21 K." in the Year frame; a note that the model is for the annual mean otherwise. ERA5's ΔT is the box-mean `skt` difference.

### Global engine strip

- `#strip`, above the time bar, shows the frame's or date's global means from the same zonal JSON (`global`): sunlight absorbed, heat radiated to space, imbalance, heat lifted by convection, Ceiling (Carnot), max power (two-box, Year frame only) and friction near the ground (W m⁻² and % of sunlight absorbed). Plain label first, symbol second; the formula is the tooltip and an (i) button opens the layer's info panel (not for the two-box item). It never computes a mean itself.
- Hidden at 1100 px and narrower: there is no room between the legend and the menu (it covered the map at 760 px and took the hover), and mobile is paused.

### Transport arrows

- A custom WebGL layer (`web/src/layers/arrows.ts`) draws the divergent energy flux (`flux_e_uv.png`) as arrows on a regular screen grid, 44 px apart (52 px on phones). Positions and directions are computed on the CPU each frame from the packed u, v codes (bilinear), which keeps the geometry unit-tested; the GPU draws them as instanced triangles with a dark halo so they read on any colour.
- Direction is the flux direction on the map (east is right, north is up). Length is proportional to the flux up to a reference, the day's 98th percentile, at which an arrow fills 90 % of a grid cell; arrows shorter than 5 px are left out. The legend says what a full-length arrow is ("full length is 6.67 × 10⁸ W m⁻¹").
- In Climate mode the arrows read `clim/{frame}/flux_e_uv.png` and use `clim.flux_ref`, one reference for all 13 frames (the 98th percentile of |F|), so lengths compare across months. `flux_e` as a raster stays Today-only.
- An "Transport arrows" checkbox in the Overlays section (`?arrows=1` until URL state lands), disabled until `flux_e` is published.

### Ocean overlay

The two limbs of the Atlantic overturning (AMOC) from Copernicus Marine GLO12 (docs/PROPOSALS-v2.md F14; `pipeline.ocean`, `web/src/ocean.ts`).

- **Pipeline.** Per published date: fetch the day's `uo`, `vo` over 100°W–25°E, 40°S–80°N, all depths; integrate the upper limb (0–1100 m, `derived.AMOC_SPLIT_M`) and the deep limb (1100 m to the sea floor) over depth (`derived.limb_transports`: U, V in m² s⁻¹ and the water thickness H); the overturning streamfunction across 26.5°N, 81°W–13°W at full resolution (`derived.overturning`, `amoc_strength`, `section_transport`); average to 0.5° with land as no flow; keep the Atlantic (`basin_mask`). Encode the day and its 30-day mean: transport magnitude (log) and depth-mean velocity, masked under 50 m (upper) or 200 m (deep) of water. At most 15 downloads a run (`MAX_FETCH`): missing dates newest first, then their windows. The daily workflow runs it as a second job after the ERA5 build, never alongside it; skipped while the secrets are unset.
- **Front end.** One `ParticleLayer` per limb, coloured (upper `#f08a5d`, deep `#6fb6f2`) and weighted: a respawning particle is kept with probability transport / `density_ref`, else parked off the map for a frame, so density follows the transport and speed the velocity (each limb on its own `speed_hi`). Drawn under the wind particles.
- **Menu:** "Ocean overturning" checkbox, limbs (both, upper, deep), averaging (30-day mean, daily, or "30-day mean, overturning only": the gyre-free files, `?ocean_part=ov`; a date without them draws the plain mean and says so) and an (i) with the manifest's `ocean.info`. Off by default. Disabled until a date has ocean files.
- **AMOC panel:** an "AMOC section" button in the same row opens `#amoc` (`web/src/amocpanel.ts`): first the conveyor belt, the upper and deep limbs' net transport at each latitude (summed across the whole basin, so eddies and gyres cancel; a ribbon as thick as the transport with arrowheads for the direction, binned to 5°), then the Atlantic's overturning streamfunction ψ(latitude, depth) for the map's date as a canvas heat map (warm clockwise, cold counter-clockwise, fixed ±25 Sv, a dashed line at 26.5° N, square-root depth axis), the strength at each latitude below it (uPlot), then the strength across 26.5° N for every date with ocean data, daily (thin) and 30-day mean (thick), each with the numbers as text. The section reads `ocean/{date}/section[_30d].json`; Climate shows the newest 30-day mean. The trend reads only the manifest's `ocean.dates`. It shares the zonal panel's place, so opening one closes the other. No URL state.
- **Legend:** a swatch per limb drawn and "Ocean overturning (GLO12, 30-day mean to DATE): across 26.5° N, upper limb X Sv north, deep limb Y Sv south; AMOC Z Sv at D m". A date without the mean falls back to daily with a note; a date without currents says so; Climate mode says there is no 1991–2020 normal and draws the newest 30-day mean. Hover: each limb's transport, speed and direction ("Upper limb: 220 m²/s, 0.20 m/s toward N").
- **Tour:** steps switch it off (the cards don't list it).

### Story mode

"Take the tour" (a button at the top of the layer menu; `?tour=N` opens it at step N) runs 12 steps in an opening, three chapters and a close, set by each card's `chapter`. Each step sets the layer, mode, frame, overlays, panel and view, and shows a card from `/story/NN-*.md`. All steps are Climate, Year unless noted.

| # | Chapter | Title | Layer | Also |
| --- | --- | --- | --- | --- |
| 1 | Opening | Two engines and an ocean | `net_toa` | |
| 2 | Engine one | Engine one: fuel | `asr_sfc` | |
| 3 | Engine one | The ceiling | `carnot` | |
| 4 | Engine one | Working at the limit | `j_ratio` | land view |
| 5 | Engine one | The split | `evap_frac` | |
| 6 | Engine two | Surplus and deficit | `net_toa` | zonal panel |
| 7 | Engine two | Transport | `div_e` | arrows |
| 8 | Engine two | Output | `ke_col` | Climate, January; mean-flow particles at 250 hPa |
| 9 | The ocean | The ocean battery | `net_sfc` | Climate, July |
| 10 | The ocean | The ocean's share | `net_sfc` | zonal panel |
| 11 | Today | The engine today | `ke_col` | Today; 100 m particles |
| 12 | Today | Explore | `net_toa` | switch, time bar, click |

The numbers the cards quote were checked against the published data on 2026-10-30 (see `docs/DECISIONS.md`); change the wording, not the data, if they ever disagree.

- **Cards** are Markdown files with a front matter block (`title`, `layer`, `mode` = `climate`/`today`/`anom` (default `today`), `frame` = `01`–`12` or `year` (required with `mode: climate`, rejected otherwise), `particles` = `off` or a wind layer (mean flow in Climate), `arrows` = `on`/`off`, `panel` = `zonal`/`none`, `chapter` (progress dots break where it changes), `view` = `lng, lat, zoom`), then 60–100 words in paragraphs with `**bold**`, `*italic*` and `` `code` `` only. They are bundled at build time (`import.meta.glob`), so a card can't drift from the code that reads it, and are rendered as DOM text, never as HTML. Tests check each card's front matter, its word count and that its layer exists.
- A step shows exactly what it lists: its layer in its mode and frame, with overlays and the zonal panel it doesn't list switched off. The map flies to the step's view (an instant jump for users who prefer reduced motion). Closing the tour, with × or Esc, or finishing it leaves the map as the last step left it.
- The card sits top-left, where the readout opens, and the readout moves below it while the tour is open. On phones it sits at the top beside the Layers button (scrolling if long), and the menu closes when the tour starts.
- Back / Next, progress dots that jump to a step, and ← → on the card (they step the tour, not the date, while the card has focus). The last step's button says Finish.

### Overview infographic

- "How the engine works": a hand-authored SVG (`web/src/overview/desktop.svg`, bundled with `?raw`) in a native `<dialog>` (`web/src/overview.ts`). It opens by itself on a first visit, over a map that keeps loading, and from the "How the engine works" button beside "Take the tour" in the menu.
- Value slots (`data-slot`) are filled from `clim/zonal/year.json` `global` (1991–2020 annual mean) with `textContent`: rounded in the text, exact in the tooltip (`<title>`). No climatology gives dashes; no value is in the SVG. Arrow widths (`data-flux`, `data-family`) are proportional within a unit family: W m⁻² flows share one scale and PW transports another, with a key on the graphic.
- Ten elements, each a focusable `role="link"` with `data-part` (`engine1`, `engine2`, `ocean`) and `data-step` (`01`–`10`, the tour card whose id starts with it). Clicking one, or Enter or Space, closes the overview and opens that tour step, so the tour's `showStep` sets the map. The accessible name carries the value ("Heat carried poleward by the ocean, up to 2.1 PW: open tour step 10").
- Chips (All, Engine one, Engine two, The ocean) dim the other parts to 0.3 opacity and outline the chosen one, with two or three sentences of explanation. "Read as text" swaps the graphic for an ordered list in tour order, with values and links. Footer: Take the tour, Explore the map, ×.
- First visit (`shouldAutoShow`): `localStorage` `ehe.overview.seen = 1` is set when it closes; every storage access is in try/catch and blocked storage shows it once per load. `?tour=N` and `?overview=0` suppress it, `?overview=1` always opens it (and is dropped from the address). Esc returns focus to the button that opened it, or to the map on a first visit.
- Desktop only: under 700 px it does not open by itself and its button is hidden (`?overview=1` still opens it). The default Playwright context is a returning visitor (`storageState` in both configs; `e2e/returning.ts` for contexts a test makes itself); `e2e/overview.spec.ts` clears it.

### URL state

The query string holds layer, mode, frame, overlays, date, centre, zoom and pinned point, and updates on every change (`web/src/urlstate.ts`):

`?layer=t_emit&mode=anom&frame=year&date=2026-10-01&center=0.25,-35.25&zoom=4&particles=wind100&arrows=1&ocean=both&pin=0.25,-35.25`

- `ocean` (`both`, `upper` or `deep`) switches the ocean overlay on and `ocean_avg=daily` picks daily currents; both are written only when on (and daily), and anything else reads as off.
- `layer`, `mode` (`climate`, `today` or `anom`), `frame` (`01`–`12` or `year`), `date`, `center` (lng,lat, 2 decimals), `zoom` and `particles` (`off`, `wind10`, `wind100` or `jet250`) are always written; `arrows=1`, `panel=zonal` and `pin=lng,lat` only when on or set. `anom=1` is read as `mode=anom`. A mode the layer can't show falls back to its default.
- It is written with `history.replaceState` (so Back isn't filled with every pan), 120 ms after the last change and after every map move.
- Reading validates each value and falls back to its default one by one: an unpublished or unbuilt layer, a date that isn't published, a bad number, a latitude beyond the map, a zoom outside 0–22. The page then rewrites the URL with the valid values. Longitudes wrap into −180…180.
- Parameters the app doesn't own (`?debug`) are kept. `?tour=N` opens the tour at step N once and is then dropped, as is `?overview`.

### Mobile

**Paused 2026-10-30 (see `docs/DECISIONS.md`):** no further mobile work for now. New features (milestone 17 onward) are desktop-only; the layout below stays as built and is not extended or fixed, and its e2e tests are not extended.

Phone layout under 700 px:

- Layer menu becomes a bottom sheet (opaque, rounded, at most 74 % of the height, scrolling inside), opened by the Layers button and closed by Done, Esc or a tap on the map.
- Readout becomes a full-height sheet.
- Particle count is halved (one per 180 px² instead of one per 90 px²).
- Touch targets are about 40 px (the small info button keeps its look and gets a 42 px tap area). Edges respect the safe-area insets. The tour card sits at the top beside the Layers button.
- Between 701 and 1100 px the time bar moves to the top.

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
7. Backfill 90 days. Time bar with play/step/pre-fetch. (**Done** 2026-10-19; the backfill finished on 2026-10-20: 90 dates, 2026-07-16 to 2026-10-13, none failed.)
8. Wind particle layer (10 m, 100 m, 250 hPa). (**Done** 2026-10-19. The transport arrows for `flux_e` came with milestone 12, where the tour needs them.)
9. Point chunks, series chunks, readout panel, 90-day chart. (**Done** 2026-10-19.)
10. Climatology job + anomaly switch. (**Done** 2026-10-19; no anomalies for the vector layers, see the layer catalogue.)
11. Human layers: `human_q` static build and `human_ratio`. (**Skipped** 2026-10-19 by decision: no dataset has been chosen and none is planned. `human_q` and `human_ratio` stay in the catalogue and show as "Not available yet"; story step 9 and the readout's Humans row need either them or a replacement if the tour is built.)
12. Story mode with the 9 Markdown cards. (**Done** 2026-10-19, with the transport arrows; step 9 is "Explore", not "Humans".)
13. Deploy: (**Done** 2026-10-19 and **deployed 2026-10-23**: Cloudflare R2 bucket seeded (90 dates, 88 419 objects, 3.3 GB), site on GitHub Pages at https://scra88le.github.io/twoenginesandanocean/, Site and Daily workflows run green on GitHub's runners including the live smoke test. See `docs/DEPLOY.md`.)
    - daily GitHub Action (`daily.yml`, with keep-alive)
    - upload to object storage (`store.py`, `deploy.py`; any S3-compatible service)
    - static hosting (`site.yml`, GitHub Pages; relocatable build)
    - URL state
    - mobile layout
    - validation log (`logs/global_means.csv` is uploaded with each run)
    - Playwright smoke test (`web/e2e-live`)
14. Pipeline foundations (docs/PROPOSALS-v2.md): (**Code and tests done** 2026-10-24, see `docs/DECISIONS.md`. **Data, 2026-10-25:** the `str` backfill is finished (90 of 90 tidy files have `lw_up`); `climatology --partial` and `rebuild` ran on the local `./out`, so the 90 dates (2026-07-16 to 10-13) have `net_sfc`, the T_r-based `carnot` and `g_max` and `manifest.radiative`, all validated `ok`. **Complete 2026-10-26:** all 12 climatology requests arrived, `climatology` and a second `rebuild` ran (35 min): 90 of 90 dates `ok`, 19 anomaly files per date including `net_sfc_anom`, the annual frame (`clim/year`, 19 layers, `radiative` ASR 242.7 W m⁻², T_r 255.78 K) and 19 layers in `clim.json`; the largest PNG is 345 kB. The wind climatology is merged into the sums but, by the 2026-10-19 decision, publishes no vector layers. **Synced 2026-10-27:** 10-14 to 10-18 were fetched day by day (15 requests, one at a time, 1–2 h each) and built from fresh tidy files, so `./out` now has the bucket's window, 2026-07-21 to 10-18, 90 of 90 `ok`, all with the new layers. **Pushed and uploaded 2026-10-27/28** (first upload: 76 066 objects), but the daily job then ran the old code (origin/main was not yet pushed) and overwrote the manifest, so the bucket is **mixed**: dates up to 10-18 carry the new files, 10-19 to 10-21 are old-code builds, 10-22 onward are new-code builds, and the manifest has `radiative` for newer dates only. **Closed 2026-10-31:** 10-19 to 10-22 were fetched and built, 10-23 and 10-24 (built by the daily job with the new code) were pulled from the bucket, `rebuild` ran over the 90 dates (2026-07-27 to 10-24; 88 rebuilt, all `ok`) and the whole data root was uploaded (13 203 objects, manifest last): the bucket is no longer mixed. Milestone 15 started before this was closed, by decision of the user, 2026-10-30.)
15. Climate data products (docs/PROPOSALS-v2.md): (**Pipeline code and tests done** 2026-10-30, 409 tests pass; see `docs/DECISIONS.md`. `pipeline.zonal` (two-box with the Kleidon fixture, transport, budget residual); `climatology` now also writes climate point chunks, climate `flux_e` and mean-flow uv files, and `clim/zonal`; run on the real data into `./out` (33 361 files, 9 min). F3 acceptance met; budget residual recorded. **Closed 2026-10-31:** the daily `zonal/{date}.json`, the climate products and the manifest's `radiative` for all 90 dates are in `./out` and in the bucket.)
16. Mode switch (docs/PROPOSALS-v2.md F1): (**Done** 2026-10-30, see `docs/DECISIONS.md`. Manifest `modes` and `default_mode`, the switch, the Climate time bar, URL `mode`/`frame`, the readout in Climate mode (climate point chunks, 12-month chart) and the legend timescale text. `flux_e` is Today-only until milestone 17. In Climate mode particles and arrows were off with a note until milestone 17.)
17. Climate overlays (docs/PROPOSALS-v2.md F3, F4): (**Done** 2026-10-30, see `docs/DECISIONS.md`. Climate-mode arrows with the shared `flux_ref`, mean-flow particles at all three levels, frame changes reload both; desktop-only. Works against local `./out`; the bucket is still the mixed state of milestones 14–15.)

18. Engine 2 and the global strip (docs/PROPOSALS-v2.md F7, F8): (**Done** 2026-10-30, see `docs/DECISIONS.md`. `web/src/zonal.ts`, `zonalpanel.ts`, `enginestrip.ts`; URL `panel=zonal`; desktop-only. Works against local `./out`: the daily `zonal/{date}.json` don't exist there until the final `rebuild`, and the bucket is still the mixed state of milestones 14–15.)
19. Story and menu (docs/PROPOSALS-v2.md F9, F10): (**Done** 2026-10-30, see `docs/DECISIONS.md`. Five menu groups with "More layers" for the advanced layers; twelve tour cards with `mode`, `frame`, `panel` and `chapter` front matter, chapter breaks in the dots, every quoted number checked against the data; desktop-only. Works against local `./out` once the manifest carries the new groups, which needs the next `rebuild`; the bucket is still the mixed state of milestones 14–15. The "How the engine works" button came with milestone 20.)
20. Overview infographic (docs/PROPOSALS-v2.md F13): (**Done** 2026-10-31, desktop only, see `docs/DECISIONS.md`. The Year frame's `global` block carries the infographic's slots; `web/src/overview.ts` and `web/src/overview/desktop.svg`; first-visit logic, menu button, tests. The phone variant is deferred with the rest of the mobile work. Works against local `./out`; nothing is uploaded, the bucket is still the mixed state of milestones 14–15.)

21. Readability (docs/PROPOSALS-v2.md F11): (**Done** 2026-10-31, see `docs/DECISIONS.md`. `rain`, `deep` and `amp` exported reversed so low is dark; a static "Loading map…" until the first raster draws; plain-first layer titles and readout names; the readout's energy-flow diagram (`web/src/energyflow.ts`). Desktop-only, local `./out`; the bucket keeps the old titles until the next `rebuild`.)
22. Globe spike (docs/PROPOSALS-v2.md F12): not started. 23 came before it, by request of the user (2026-10-31):

23. Ocean overlay (docs/PROPOSALS-v2.md F14): (**Code and tests done** 2026-10-31, see `docs/DECISIONS.md`: `pipeline.ocean`, the AMOC formulas in `pipeline.derived`, `ocean` CLI command and daily job, the coloured and density-weighted particle layer, controls, legend, URL state, fixtures. **Open:** never run against Copernicus Marine (unreachable from the sandbox it was written in); needs the two secrets and a first run, then the checks listed in the decision entry.)

## Acceptance criteria

- [ ] The daily job runs unattended for 7 consecutive days, with a new date each day. (**Open:** one manual run on GitHub's runners succeeded on 2026-10-23 (credentials checked, state downloaded in 80 s, four new dates requested, state saved to the bucket), but the schedule has not yet run unattended for 7 days. Its logic is also tested end to end against a local folder and fake CDS and S3 clients.)
- [ ] All 24 layers render for each of the last 90 days, with legend, units and info panel. (**Partly:** 22 of 24, because the two human layers were skipped on 2026-10-19, so reword to 22. Checked 2026-10-20: all 22 layers, with their vector and anomaly files, info text and units, exist for each of the 90 published dates (2026-07-16 to 2026-10-13), and each has all 648 point tiles.)
- [x] Global-mean validation passes for every built date, and the log CSV exists. (90 of 90 published dates have an `ok` row on 2026-10-20, plus the row of 2026-07-15, a date that has since left the window; the log is a history and is uploaded with every daily run.)
- [x] Derived-layer tests pass, including the three fixtures.
- [ ] Clicking any land cell shows the full readout and 90-day chart within 1 s. (**Met locally:** under 0.8 s on a cold load and 41 ms for a click, from the local dev server. The deployed site's smoke test clicks a point and waits for the readout and chart, but does not time it, so recheck the latency from the bucket by hand.)
- [x] Anomaly mode works for every natural layer, on a diverging scale centred on zero. (For the 18 non-vector natural layers; the vector layers have none by decision, 2026-10-19.)
- [x] Wind particles animate at all three levels over any raster.
- [x] Story mode runs through all 9 steps, forwards and back, and each step sets its layer and view.
- [x] A copied URL restores layer, date, view and pinned point. (Plus anomaly, overlays and arrows; Playwright restores a copied URL in a fresh browser context.)
- [x] A deliberately failed run (bad API key) leaves yesterday's site intact. (Tested locally: a fake CDS client that fails its authentication check leaves the store byte-for-byte unchanged, as do failures while building or uploading. The real client rejects a dummy key with a 401 at that same check, verified 2026-10-19. Not yet tried on Actions.)
- [x] Performance and payload targets are met. (Measured 2026-10-19 on this laptop, production build, real data: first map 2.0 s at 20 Mbit/s with 40 ms latency, uncompressed; date step 226 ms; first map 1 341 kB gzipped, 998 kB without the basemap; every PNG under 400 kB, the largest 344 kB; 60 fps panning with particles on an integrated Intel Arc GPU. **Not tested:** a 2020-era laptop, and the deployed host. The payload figure assumes the host compresses text, as GitHub Pages and Cloudflare do.)
- [x] Data credits appear in the footer and info panels.

## Open questions and risks

| Item | Risk or question | Proposed handling |
| --- | --- | --- |
| Human energy data | **Skipped 2026-10-19.** Which gridded anthropogenic heat flux dataset, and is its licence compatible? | Shortlist published datasets (e.g. Varquez et al., 2021, *Scientific Data*). Fall back to OWID country totals. |
| `div_e` noise | Daily 0.5° `p86.162` is dominated by grid-scale noise | **Decided 2026-10-18:** smooth with implicit diffusion (see Derived quantities) |
| `flux_e` content | Raw `p75.162`/`p76.162` are dominated by circulation that carries no energy poleward | **Decided 2026-10-18:** draw only the divergent part, from smoothed `div_e` |
| KE generation | No direct ERA5 field; `bld` covers boundary-layer friction only | Later: check the definition of `p64.162`, or compute pressure-gradient work |
| Max-power model | Single-column, no storage; absolute values are illustrative | Land-only display; compare against Kleidon's published estimates; label as model-based |
| Data lag | ~6 days | State it clearly; later add ECMWF open data / GFS for same-day winds |
| CDS queue | Hours-long waits, outages; Actions jobs are killed after 6 h | Submit without waiting, track IDs in `/state/pending.json`, collect on the next run; 10-day rolling catch-up; never overwrite good data |
| Cron shutdown | GitHub disables scheduled workflows after 60 days with no repo activity | Add a keepalive step (e.g. a monthly empty commit or the API "enable workflow" call), or check it during monthly maintenance |
| Storage growth | Per date: 6.3 MB of field PNGs plus 13.5 MB of point chunks (648 × 20.8 kB). For 90 days: ~570 MB of fields, ~1.2 GB of points and ~1.2 GB of series, about 3 GB, more with anomalies | Monitor against free tiers (R2: 10 GB). Gzip shrinks point and series chunks to about 0.6 of their size (measured 2026-10-19; all-masked ocean tiles of land-only layers to almost nothing), so serving them gzip-encoded is an option |
| Write operations | Series rebuild is 648 tiles × 24 layers ≈ 15.5k objects/day (~470k/month), plus fields and points | Within R2's free tier for writes, but monitor; skip uploading unchanged objects |
| PNG size | The low byte of a uint16 is noise when the step is finer than the data | **Resolved** with per-layer resolutions: 91–344 kB per file on 2026-10-01. Re-check on stormy winter dates |
| Basemap | Licence and attribution | **Resolved:** Natural Earth (public domain), credited in the footer. Place labels are not included yet |

Record answers to these in `docs/DECISIONS.md` as they are resolved.
