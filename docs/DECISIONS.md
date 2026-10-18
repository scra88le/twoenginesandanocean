# Decisions

A log of deviations from the plan and choices made during the build. Newest first.

## 2026-10-18 — Milestone 4: encoding, storage layout and manifest

- **New modules:**
  - `pipeline.layers`: the catalogue of all 24 layers, with IDs, titles, groups, units, colour scales, display and encode ranges, resolutions and anomaly ranges.
  - `pipeline.encode`: quantisation, decoding and PNG packing.
  - `pipeline.publish`: encoding a date, the atomic write, the manifest, and pruning to 90 days.
  - `cli build`: tidy → layers → PNGs → manifest.
- **Fixed resolution instead of spreading each range over 65 533 levels.** With full-range steps (for example 0.008 W m⁻² for `asr_sfc`), neighbouring cells differ by hundreds of codes, the low byte is noise, and 23 of 26 files were 403–457 kB (11.4 MB per date). Per-layer resolutions about what the data can resolve brought the files to 91–344 kB (6.3 MB per date), with every round-trip error within half a step. The manifest's `scale` is the resolution, so the packing formula is unchanged. Chosen steps:
  - most W m⁻² fluxes: 0.1–0.25 W m⁻²;
  - `t_emit`: 0.02 K; `carnot`: 0.02 %;
  - wind speeds: 0.02–0.05 m s⁻¹; wind components: 0.1 m s⁻¹, enough for particle advection, and it gives `jet250_uv` room (392 → 294 kB);
  - `div_e`: 1 W m⁻²; `flux_e`: 1e6 W m⁻¹, against typical values of 2e8;
  - log layers: 0.002 decades (0.46% relative);
  - `j_ratio`: 0.002, so its ±50 range fits.
- **Vector layers are two files**: the magnitude as an ordinary scalar PNG, plus `{layer}_uv.png`. The raster path is then the same for every layer, and the front end never computes a wind speed.
- **Scalar PNGs are RGB with B = 0**, so the alpha channel only matters for the `_uv` files. Writing an RGBA PNG with A = 0 texels keeps their RGB on the Python side (tested). The browser side is milestone 5.
- **Encode ranges** are set from physical limits and the 2026-10-01 data, wide enough that real values aren't clipped. The exception is log layers: values between 0 and the encode floor are raised to the floor. On 2026-10-01 that was 6278 `precip` cells under 0.001 mm/day and 18 `p_lift` cells. They are counted as clipped in the build output.
- **Publishing:**
  - A date's files go into `fields/.{date}.tmp/` and are renamed into place only once all are written. Republishing a date swaps the old directory out the same way.
  - `manifest.json` is written last via a temporary file and `os.replace`, then dates beyond the newest 90 are deleted.
  - Tests simulate a failed file write and a failed manifest write; both leave the published site byte-for-byte unchanged.
- **Manifest contents** (version 1, about 14 kB):
  - built time, sorted dates, grid, reserved codes, and file path templates;
  - for every layer, in catalogue order: title, group, units, colour scale, display range (or "auto"), log flag, centre, vector flag, and the encode, uv and anomaly ranges with their scale and offset;
  - the Copernicus attribution text.
- **Not in this milestone:** point and series chunks (milestone 9, as the spec orders them) and the per-date validation gate (step 6 of the daily run; milestone 13 has the validation log). `build` publishes without validating.

## 2026-10-18 — Milestone 3: derived quantities

- **`pipeline.derived`** holds every formula: the point formulas, the spherical solver, and `compute_layers`, which returns all 22 natural layers in catalogue units (`carnot` in %, `ke_col` in MJ m⁻², `precip` in mm/day). Each layer is a `LayerField`: values, a boolean `masked` (ocean for land-only layers, threshold masks), and u/v components for vector layers, whose `values` are the magnitude. NaN outside the mask means missing data. This maps onto the reserved codes 0 and 1 in milestone 4.
- **Spec fixtures pass:** T_e = 255.06 K, η_C = 15%, J_opt = 100 W m⁻², G_max = 8.86 W m⁻². A test also checks G_max against a brute-force maximum of G(J).
- **Solver tests:** the Laplacian matches analytic spherical harmonics (degree 1 and the (2, 1) harmonic) to within 0.1% of the field's scale; it integrates to zero; the Poisson solve recovers a random potential; the smoothing is exactly the implicit-diffusion operator, keeps constants and the global mean, and is the identity at L = 0; and the discrete Gauss identity holds exactly.
- **Real-data check of the solver.** With the unsmoothed `p86.162`, the solver's northward transport matches ERA5's own `p76.162` integrated around each latitude circle on all five dates (rms difference 0.012–0.020 PW, against 2.6–7.4 PW of signal). The peak transport is 4.5–5.1 PW on most dates, as in the literature; 15 January 2026 has a 15.9 PW northern peak, which ERA5's own flux also shows. With this check passed, `p75.162` and `p76.162` are **dropped from the fetch**.
- **Smoothing length L = 100 km** (default `SMOOTH_LENGTH_M`; the planned 300 km was a placeholder). On all five dates (2025-10-15, 2026-01-15, 2026-04-15, 2026-07-15, 2026-10-01), L = 100 km cuts the share of `div_e` rms at scales below a 5×5 block of cells from 52–59% to 5.7–6.7%, under net TOA radiation's 8%. It changes the meridional transport by 0.024–0.032 PW rms (about 1%). L = 300 km changes the transport by 0.11–0.18 PW and removes little more noise.
- **What remains in daily `div_e` is weather, not noise.** At L = 100 km the 2nd–98th percentile still spans about −700 to +650 W m⁻² (net TOA: −206 to +103). The variability is 3× larger in the storm tracks (rms 300–530 W m⁻² at 30–90°) than in the tropics (155). The likely reason is that a single day's divergence includes the energy moved around by passing weather systems. Zonal means still follow net TOA (tropics +25 to +31, polar caps −170 to −211 W m⁻²). So a daily map shows weather-scale sources and sinks, and the tropics-to-poles pattern appears only in averages. **A possible later choice for the project owner:** show `div_e` and `flux_e` as a running mean (for example 30 days) for the story step. Not decided.
- **Encode ranges:** `div_e` ±2000 W m⁻², `flux_e` components ±1.5e9 W m⁻¹, from the five dates. The largest values were 1793 W m⁻² and 1.06e9 W m⁻¹; the headroom is because five dates can't cover every extreme, and quantisation steps stay small (0.06 W m⁻²; 4.6e4 W m⁻¹ against typical values of 2e8). Display ranges stay "auto" (2nd–98th percentile).
- **`j_ratio` is also masked where R_s < 10 W m⁻²**, because J_opt → 0 there and the ratio blows up. The spec didn't cover this case.
- **`carnot` hatching:** clamped cells are exactly 0, so the front end can hatch cells whose value is the lowest valid code. No extra data file is needed.
- **Real-data sanity, 2026-10-01:**
  - `t_emit` global mean 255.1 K.
  - `carnot`: median 10.6%, max 34%; 2.6% of cells clamped.
  - `g_max` over land: median 1.2, 98th percentile 12.2 W m⁻².
  - `j_ratio` over land: median 0.82, near the max-power value of 1 that Kleidon's view predicts.
  - `p_lift` global mean 1.05 W m⁻².
  - `diss_bl` global mean 2.7 W m⁻².
  - Divergent `flux_e`: median 2.4e8 W m⁻¹.

## 2026-10-18 — `div_e` is smoothed; `flux_e` shows the divergent flux

Decided by the project owner, choosing options 1 and 3 below (evidence in the milestone 2 entry).

- **`div_e`** is ERA5 `p86.162` smoothed on the sphere by implicit diffusion: solve (1 − L²∇²) D_s = D. This damps grid-scale noise while leaving the global mean and large-scale pattern alone, and it is isotropic on the sphere, so there are no polar artefacts as with a lat-lon box filter. A wave of wavelength λ is damped by a factor of 1 / (1 + (2πL/λ)²). The length scale L is a config value (`smooth_length_m`, default 300 km at first, tuned to 100 km in milestone 3, see above), tuned so that the fine-scale share of the rms is close to that of net TOA radiation (about 10%). The info panel states L and that the field is smoothed.
- **`flux_e`** is the divergent part of the energy flux: solve ∇²χ = D_s − ⟨D_s⟩ and draw F_div = ∇χ. Its divergence is `div_e`, so the arrows run from energy sources (tropics) to sinks (poles), which is the transport the story step is about. The circulating part (k × ∇ψ in the Helmholtz decomposition) is left out. It dominates the raw `p75.162`/`p76.162` field but carries nothing across a latitude circle. The info panel says so. The global mean ⟨D_s⟩ (−0.04 W m⁻² on 2026-10-01) is removed so the equation has a solution.
- **One solver for both**, in `pipeline.derived`: a finite-volume Laplacian on the cell-centred 0.5° grid, FFT in longitude and a tridiagonal solve in latitude for each zonal wavenumber. Numpy only, no new dependency.
- **Checks** (milestone 3): smoothing preserves the global mean; ∇·F_div reproduces the input; the zonal integral of northward F_div across each latitude circle equals the area integral of the source poleward of it (exact at the discrete level for a finite-volume operator). On real data with unsmoothed D, the zonal-mean northward F_div should match the zonal mean of raw `p76.162`, which checks the solver against ERA5's own flux.
- **`p75.162` and `p76.162`** are no longer layer inputs. They stay in the fetch until that real-data check passes, then they can be dropped.
- **Rejected:** deriving `div_e` from the surface and TOA energy budget (option 2). It needs `str` fetched and ignores heat storage, and the smoothed ERA5 field stays closer to the source variable.
- **Encode ranges** for `div_e` and `flux_e` move to milestone 3. They depend on L and are set from a sample of dates across seasons.

## 2026-10-17 — Milestone 2 findings

- **Dataset IDs confirmed** in the CDS catalogue: `derived-era5-single-levels-daily-statistics`, `derived-era5-pressure-levels-daily-statistics`, `reanalysis-era5-single-levels`, `reanalysis-era5-single-levels-monthly-means`. Latest daily data was 2026-10-11 on 2026-10-17, so the lag is 6 days, as expected.
- **Vertical integrals are in the daily product**, so the hourly fallback isn't needed. Downloaded for 2026-10-01 and confirmed from the GRIB parameter IDs: `vike` = 162059, `vited` = 162086, `vitee` = 162075, `viten` = 162076, matching the spec's `p59.162`, `p86.162`, `p75.162` and `p76.162`.
- **Pressure-level daily** offers `daily_mean`, `daily_minimum` and `daily_maximum` only (no `daily_sum`), and includes 250 hPa. That is enough for the jet-stream layer.
- **Three requests per date**, not two. A request carries one `daily_statistic`, and the single-levels dataset needs both `daily_mean` and `daily_sum`.
- **Land-sea mask.** The spec didn't say where the land mask for `g_max` and `j_ratio` comes from. `land_sea_mask` is available in the same daily-statistics product, so it rides along in the means request.
- **`str` is not fetched.** No layer uses surface net longwave, so it is left out of the requests. `convert_fields` still flips it if present.
- **KE generation lead.** The daily product has `vertical_integral_of_energy_conversion`, which may be the conversion term the "KE generation" open question needs. Not yet investigated.
- **Credentials.** `ecmwf-datastores-client` (used by `cdsapi` 0.7.7) reads `~/.ecmwfdatastoresrc`, not `~/.cdsapirc`, so `pipeline.fetch.read_credentials` reads `CDSAPI_URL`/`CDSAPI_KEY` or `~/.cdsapirc` itself.
- **Licences.** The CDS returns 403 until the licence for each dataset is accepted on the website. This is a manual step for the account owner.
- **Result format.** CDS returns a zip of one NetCDF per variable (despite the `.nc` name), each with a length-1 `valid_time` dimension. `pipeline.load` handles this and refuses unsafe member names.
- **Monthly-means accumulation (resolved).** Accumulated fields are mean *daily* accumulations (`GRIB_stepType=avgad`). October 2025 `tsr` ÷ 86 400 = 245.4 W m⁻² and `tp` × 1000 = 2.94 mm/day, so the daily conversions apply unchanged.
- **Real-data check, 2026-10-01** (0.5° grid, area-weighted global means): `tsr` 243.6, `olr` 243.1, `ssr` 164.5 W m⁻²; `tp` 3.07 mm/day; land fraction 28.9%; latent heat 110 W m⁻² over ocean and 42 over land; sensible heat 11.5 and 28.7. All within the validation ranges, no missing cells, and the global-mean divergence of the energy flux is −0.04 W m⁻².
- **`fetch` is idempotent and non-blocking.** `fetch_date` skips downloaded files, downloads finished requests (via a `.part` file), resubmits failed ones, and keeps queued request IDs in `raw/pending.json`. `--wait` polls with exponential backoff capped at 5 minutes.

### What `div_e` and `flux_e` should show (decided 2026-10-18, see above)

Evidence from 2026-10-01:

- **`div_e`** (`p86.162`, W m⁻²): 2nd–98th percentile is −1200 to +966, so an "auto" colour range would be dominated by noise. Its rms is 535 W m⁻², and 55% of that is variation finer than a 5×5 block of cells (for net TOA radiation, 8%). The signal underneath is physically right: zonal means have the correct sign and shape (30–60°N −24, 0–30°N +28, 60–90°N −221 W m⁻², against net TOA −51, +50 and −164).
- **`flux_e`** (`p75.162`, `p76.162`, W m⁻¹): the local rms is 2.6e10, but the zonal-mean northward flux is at most 1e9. The vertically integrated total-energy flux contains a large component that circulates without delivering energy, so arrows drawn from the raw field would show circulation, not poleward transport.

Options:

1. **Smooth `div_e`** (for example a spectral truncation at about T42, or a 5×5 box) and say so in the info panel. Cheap, and keeps the ERA5 variable.
2. **Derive `div_e` from the energy budget:** net TOA radiation minus the net surface flux (`tsr − olr − (ssr − lw_up) + le + h`, signs as in the sign-flipped fields). It's smooth, and each term is traceable, but it ignores storage and needs `str` fetched.
3. **For `flux_e`, show only the divergent part** of the flux: solve ∇²χ = `div_e` and draw ∇χ, so the arrows point from sources to sinks. It would be built from the smoothed or budget-derived divergence and computed in `pipeline.derived`.

Until this is decided the `div_e` and `flux_e` encode ranges are not set. Display-range clipping seen on this date (so milestone 4 sets encode ranges from data, not the 10% rule): `lh` reaches 703 W m⁻² (5.9% of area is outside 0–300), `bld` reaches 104 W m⁻² (1.0% above 20), `ke_col` reaches 14 MJ m⁻² (6.2% above 6), and `precip` reaches 340 mm/day (display range stops at 100).

## 2026-10-17 — Milestone 1 scaffold

- **Python versions.** The package declares `requires-python >=3.12` and CI runs on 3.12, as specified. Local development uses a 3.14 venv, because 3.12 isn't installed on this machine. All dependencies installed from wheels on 3.14.
- **Tooling.** Ruff for Python lint (rules E, F, I, UP, B, line length 100). ESLint with typescript-eslint, `tsc --noEmit` and Vitest for the front end.
- **Dev data root.** `npm run dev` serves `../out` under `/data/` through a small Vite middleware in `web/vite.config.ts`, so the front end fetches `/data/manifest.json`, `/data/fields/...` and so on. The production base URL will be configurable in milestone 13.
- **Playwright** is run as `npm run e2e`. `npx playwright test` also works.

## 2026-10-17 — Spec review before milestone 1

- **Sign flips happen once.** `pipeline.convert` flips `ttr`, `slhf`, `sshf` and `str` and renames them `olr`, `le`, `h` and `lw_up`. `pipeline.derived` never negates an input. This replaces the earlier notation (`OLR = −ttr` on fields that were already flipped), which would have flipped twice. `net_toa = tsr − olr`.
- **Package layout.** `pipeline/pyproject.toml` with the package in `pipeline/src/pipeline/`. Commands run from the repo root. Local output goes to a repo-root `out/`, which the web dev server uses as its data root.
- **Regridding.** Replaced 2×2 block averaging with a conservative remap. ERA5's 1440 × 721 point-centred grid includes the poles, so it can't be split into 2×2 blocks. The remap uses a 3 × 3 stencil with [½, 1, ½] weights per axis, multiplied by cos(lat). The 0.5° grid is cell-centred with no pole rows.
- **Reserved codes.** 0 = no data, 1 = masked, 2–65535 = valid. The no-data validation counts only code 0, so land-only layers pass.
- **Log packing.** Layers with log scales are packed in log₁₀ space, because linear uint16 packing can't resolve the lower end of the `human_q` and `human_ratio` ranges.
- **Encode vs display ranges.** Encode ranges are fixed per layer in `pipeline.layers` and are separate from display ranges. This resolves several conflicts:
  - "auto" display ranges (`div_e`, `flux_e`): their encode ranges are set in milestone 2.
  - `carnot`: encoded 0–45% to cover the 40% validation bound.
  - Layers with negative values (`j_conv`, `lh`, `evap_frac`): encode ranges extended below zero.
  - Anomalies: symmetric linear ranges set per layer.
- **`flux_e`** uses the vector RGBA packing (u in R+G, v in B+A).
- **Point and series chunks** are uint16, not int16, with the same packing as the PNGs.
- **Texture upload.** Premultiplied alpha and colour-space conversion are turned off, and textures use nearest sampling. Covered by a Vitest decode test.
- **CDS requests don't block the run.** Requests are submitted without waiting, their IDs are tracked in `/state/pending.json`, and results are collected on the next run, because Actions jobs are killed after 6 h.

### Still open

- Nothing from milestone 2. (Milestone 3 raised one optional choice: a running mean for `div_e` and `flux_e`.)
