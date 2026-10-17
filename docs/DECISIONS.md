# Decisions

A log of deviations from the plan and choices made during the build. Newest first.

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

### Open decision: what `div_e` and `flux_e` should show

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

- What `div_e` and `flux_e` should show (see above), and therefore their encode ranges.
