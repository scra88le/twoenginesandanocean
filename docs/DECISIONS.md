# Decisions

A log of deviations from the plan and choices made during the build. Newest first.

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
