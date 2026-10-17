# Decisions

A log of deviations from the plan and choices made during the build. Newest first.

## 2026-10-17 — Milestone 2 findings

- **Dataset IDs confirmed** in the CDS catalogue: `derived-era5-single-levels-daily-statistics`, `derived-era5-pressure-levels-daily-statistics`, `reanalysis-era5-single-levels`, `reanalysis-era5-single-levels-monthly-means`. Latest daily data was 2026-10-11 on 2026-10-17, so the lag is 6 days, as expected.
- **Vertical integrals are in the daily product**, so the hourly fallback isn't needed for them: `vertical_integral_of_kinetic_energy`, `..._divergence_of_total_energy_flux`, `..._eastward_total_energy_flux` and `..._northward_total_energy_flux` all pass the CDS constraint check with `daily_mean`. The mapping from these names to the spec's parameter IDs (`p59.162` etc.) is still to be checked against a downloaded file.
- **Pressure-level daily** offers `daily_mean`, `daily_minimum` and `daily_maximum` only (no `daily_sum`), and includes 250 hPa. That is enough for the jet-stream layer.
- **Three requests per date**, not two. A request carries one `daily_statistic`, and the single-levels dataset needs both `daily_mean` and `daily_sum`.
- **Land-sea mask.** The spec didn't say where the land mask for `g_max` and `j_ratio` comes from. `land_sea_mask` is available in the same daily-statistics product, so it rides along in the means request.
- **`str` is not fetched.** No layer uses surface net longwave, so it is left out of the requests. `convert_fields` still flips it if present.
- **KE generation lead.** The daily product has `vertical_integral_of_energy_conversion`, which may be the conversion term the "KE generation" open question needs. Not yet investigated.
- **Credentials.** `ecmwf-datastores-client` (used by `cdsapi` 0.7.7) reads `~/.ecmwfdatastoresrc`, not `~/.cdsapirc`, so `pipeline.fetch.read_credentials` reads `CDSAPI_URL`/`CDSAPI_KEY` or `~/.cdsapirc` itself.
- **Licences.** The CDS returns 403 until the licence for each dataset is accepted on the website. This is a manual step for the account owner.

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

### Still open (milestone 2)

- Availability of vertical integrals in the daily product, and the pressure-level daily dataset ID.
- Accumulation period of accumulated fields in the monthly-means product.
- Encode ranges for `div_e` and `flux_e`.
