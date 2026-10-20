# Deploying the Earth Heat Engine Map

> **Status:** everything here is written and tested locally (against a folder standing in for the
> bucket, and fake CDS and S3 clients), but **has not been run against a real bucket, GitHub
> Actions or Pages**: the repository had no GitHub remote when it was written. The provider steps
> come from their documentation as of October 2026; check them against the current docs, and
> expect to fix small things on the first real run.

## How it fits together

```
 GitHub Actions                      object storage (R2 or S3)               visitors
┌────────────────────┐  upload   ┌────────────────────────────┐   GET    ┌──────────────┐
│ daily.yml          │──────────▶│ manifest.json   (no-cache) │◀─────────│ the browser  │
│  pipeline daily    │ manifest  │ fields/ points/ series/    │  (CORS)  │              │
│  (CDS → maps)      │   last    │ clim/ logs/ state/         │          │              │
└────────────────────┘           └────────────────────────────┘          │              │
┌────────────────────┐  deploy   ┌────────────────────────────┐   GET    │              │
│ site.yml           │──────────▶│ static site (Pages)        │◀─────────│              │
│  npm run build     │           │ index.html, JS, CSS, cards │          └──────────────┘
└────────────────────┘           └────────────────────────────┘
```

- **The data and the site are separate.** The site is built once per code change and knows
  only the address of the bucket (`VITE_DATA_URL`). The data changes daily and never touches the
  site's build.
- **A daily run never waits on CDS.** It submits requests, saves their IDs in
  `state/pending.json`, and collects finished ones on a later run. A date is published once all
  three of its requests (single-level means, single-level sums, pressure levels) are in.
- **`manifest.json` is written last,** so until it changes the old site keeps working. A failed
  run leaves yesterday's site exactly as it was. Files of dates that fell out of the 90-day window
  are deleted only after the new manifest is in place.

## One-time setup

### 1. The bucket (Cloudflare R2, the chosen provider)

Done on the Cloudflare dashboard, with your own account (R2 asks for a payment method even
within its free tier; the code works the same with any S3-compatible service).

1. Sign up at cloudflare.com and open **R2 Object Storage**; enable it.
2. **Create bucket** (for example `earth-heat-engine`, automatic location).
3. **Public access.** In the bucket's *Settings*, either connect a **custom domain** (best for
   a real site; the domain must be on Cloudflare) or enable the **`r2.dev` public address**
   (quick to start; Cloudflare rate-limits it and says it is not meant for production). Note the
   address: it is your `DATA_URL`.
4. **CORS.** In the bucket's *Settings → CORS policy*, add (the origin is the site's address
   without a path):

   ```json
   [
     {
       "AllowedOrigins": ["https://scra88le.github.io"],
       "AllowedMethods": ["GET", "HEAD"],
       "AllowedHeaders": ["*"],
       "MaxAgeSeconds": 3600
     }
   ]
   ```

   Without this the page loads but every data request is blocked, which shows as "No data for…"
   and CORS errors in the browser console. Add `http://localhost:5173` while testing locally.
5. **API token.** *R2 → Manage API tokens → Create API token*, permission **Object Read &
   Write**, limited to this one bucket. Copy the **Access Key ID**, the **Secret Access Key**
   and the account's S3 address (`https://<account-id>.r2.cloudflarestorage.com`); the secret is
   shown only once.

### 2. The repository

The repository is `scra88le/twoenginesandanocean` (public), Pages is enabled with GitHub Actions
as its source, and `SITE_URL` is already set to `https://scra88le.github.io/twoenginesandanocean/`.
The rest, once the bucket exists (each `gh secret set` asks for the value, so it never appears in
your shell history or in a chat):

```bash
gh secret set CDSAPI_URL        # https://cds.climate.copernicus.eu/api
gh secret set CDSAPI_KEY        # your CDS personal access token
gh secret set AWS_ACCESS_KEY_ID
gh secret set AWS_SECRET_ACCESS_KEY
gh variable set STORE_URL        --body "s3://earth-heat-engine"
gh variable set S3_ENDPOINT_URL  --body "https://<account-id>.r2.cloudflarestorage.com"
gh variable set DATA_URL         --body "https://<the bucket's public address>"
```

| Name | Kind | Value |
| --- | --- | --- |
| `CDSAPI_URL` | secret | `https://cds.climate.copernicus.eu/api` |
| `CDSAPI_KEY` | secret | your CDS personal access token (the licences for both ERA5 daily-statistics datasets must already be accepted on the CDS website) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | secrets | the R2 API token's key pair |
| `STORE_URL` | variable | `s3://<bucket>` (optionally `s3://<bucket>/<prefix>`) |
| `S3_ENDPOINT_URL` | variable | `https://<account-id>.r2.cloudflarestorage.com` (AWS S3: leave empty) |
| `DATA_URL` | variable | the bucket's **public** address, no trailing slash |
| `SITE_URL` | variable | already set; the smoke test runs against it after each deploy and daily build |

### 3. Seed the data

The daily job only attempts the last 10 days, so the first 90 come from your machine:

```bash
export CDSAPI_URL=... CDSAPI_KEY=...                       # or ~/.cdsapirc
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_ENDPOINT_URL=... AWS_DEFAULT_REGION=auto
pip install -e "./pipeline[deploy]"

python -m pipeline.cli backfill --days 90 --out ./out --wait   # hours: the CDS queue
python -m pipeline.cli climatology --out ./out --wait          # about 6 GB of monthly files
python -m pipeline.cli rebuild --out ./out                     # adds anomaly maps to the dates
python -m pipeline.cli upload --store s3://<bucket> --out ./out
```

`upload` skips whatever the bucket already has, so it can be repeated and resumed. The full data
root for 90 dates is 3.4 GB in 88 420 objects.

### 4. First deploy

1. **Actions → Site → Run workflow.** It builds with `DATA_URL`, publishes to Pages and runs the
   smoke test against the result.
2. **Actions → Daily build → Run workflow.** Check the log: it should download the state, find
   nothing to build (or build the newest date) and finish green.
3. Open the site. Click a point and check that the readout and chart appear.

## Day to day

- **It runs by itself** at 07:23 UTC. A failed run (a CDS outage, a date that failed validation)
  shows red and GitHub emails the repository's watchers. The previous day's site stays up.
- **A date that fails validation** is skipped and logged (`logs/global_means.csv` has a `failed`
  row and the problems) and the run is marked failed; other dates still publish.
- **Run by hand:** Actions → Daily build → Run workflow; the `days` input widens the window if
  you were away.
- **Change what a date contains** (a new layer, a different encoding): `rebuild` re-runs every
  published date from the cached tidy files in `./work` and `upload` publishes the result.
  Dates whose tidy file has expired need `backfill` again.
- **Roll back a bad publish:** keep a copy of `manifest.json` (turn on bucket versioning, or
  download it now and then). Re-uploading the previous manifest makes the site list the previous
  dates again. Each publish deletes the files of dates beyond the 90-day window, so the oldest
  date in the old manifest may be gone and show "No data"; everything else is still there. The
  series files are self-describing, so they stay correct either way.
- **Cloudflare Pages instead of GitHub Pages:** skip `site.yml`'s `deploy` and `smoke` jobs and
  add `npx wrangler pages deploy web/dist --project-name <name>` after the build, with
  `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets. The CORS origin is then your
  `*.pages.dev` or custom domain.

## Costs and limits

- **Storage:** 3.4 GB for 90 days: maps 0.9 GB, point chunks 1.4 GB, series 1.0 GB,
  climatology 0.2 GB. R2's free tier is 10 GB.
- **Writes:** a daily run uploads about 15 000 objects (the rebuilt series plus a day's maps and
  points), about 450 000 a month. R2's free tier is 1 million write operations a month.
- **Runner time:** the run downloads about 425 MB of state (about 2 000 files; measured against
  a local folder: 3 s), builds each new date (about 15 s), and uploads about 15 000 objects.
  My estimate is 10–20 minutes on a runner; it has not been measured there. Public repositories have no Actions minute limit; private ones have
  2 000 free minutes a month.
- **Cron shutdown:** GitHub disables scheduled workflows after 60 days with no repository
  activity. The daily workflow's last step calls the "enable workflow" API, which resets that
  clock; if it ever fails (check the log), a monthly empty commit does the same. This has not been
  verified against a real 60-day gap. Check that the schedule is still on during monthly
  maintenance (Actions → Daily build shows the last scheduled run).

## What watches it

- **The daily run's exit code** (red on any failure, including a failed validation).
- **The smoke test** (`web/e2e-live`, `npm run smoke` with `SITE_URL` set): the site loads, the
  manifest is no more than 14 days old (`MAX_AGE_DAYS`), the map drew pixels, a click shows the
  readout and chart (so the bucket's CORS is right), no request failed, and the manifest is not
  cached for long. It runs after each daily build and each site deploy.
- **The validation log** `logs/global_means.csv`: one row per date with the global means that
  the validator checks.

## When something goes wrong

| Symptom | Likely cause |
| --- | --- |
| The page loads but shows "No data for…" and console CORS errors | The bucket's CORS rule is missing or has the wrong origin |
| `Not set: …` at the top of a daily run | A secret or variable from the table above is missing |
| `401 Unauthorized` in a daily run | The CDS key is wrong or expired (it is checked first, before anything is changed) |
| `403` from CDS naming a licence | The ERA5 daily-statistics licences are not accepted on the CDS website |
| `Number queued requests for this dataset is temporarily limited` | CDS's per-user queue limit; the job keeps two requests per dataset and retries on the next run |
| The newest date is days behind | CDS is slow (requests can sit for hours); the smoke test starts failing after 14 days |
| A date is missing from the map | It failed validation: see its row in `logs/global_means.csv` |
| The site 404s on its own files | `DATA_URL` or Pages' source setting is wrong; the build is relative, so any path works |

## Security

- The CDS key and the storage credentials are repository secrets and are only handed to the
  daily job; nothing prints them. Scope the storage credential to the one bucket.
- The site is static and has no accounts or backend. The only requests it makes are for files in
  the bucket and its own assets.
