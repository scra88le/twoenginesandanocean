# Earth Heat Engine Map

A windy.com-style global map that explains the atmosphere as a heat engine, following Axel
Kleidon's thermodynamic view of the Earth system. A daily Python pipeline turns ERA5 reanalysis
data from the Copernicus Climate Data Store into packed images; a static front end (MapLibre and
WebGL) draws them: 22 layers from sunlight absorbed to wind and rain, wind particles, transport
arrows, anomalies against 1991–2020, a point readout with a 90-day chart, and a guided tour.

Data: *Generated using Copernicus Climate Change Service information: ERA5 (Hersbach et al.,
2020), via the Copernicus Climate Data Store.* Coastlines: Natural Earth (public domain).

## Where things are

| | |
| --- | --- |
| `CLAUDE.md` | The specification, commands, encoding, layer catalogue and milestones |
| `docs/DECISIONS.md` | Every deviation from the plan and every choice made, with the evidence |
| `docs/DEPLOY.md` | Setting up the bucket, the secrets and the workflows, and running it day to day |
| `pipeline/` | Python 3.12 package: fetch, convert, derive, encode, validate, publish, daily job |
| `web/` | Vite + TypeScript front end, with Vitest and Playwright tests |
| `story/` | The nine cards of the guided tour |

## Quick start

```bash
# Pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./pipeline[dev]"
pytest pipeline

# Front end (serves ./out as its data)
cd web && npm install
npm run dev
npm test && npm run e2e
```

Getting data into `./out` needs a CDS account with the two ERA5 daily-statistics licences
accepted: see **Commands** in `CLAUDE.md` (`fetch`, `build`, `backfill`, `climatology`) and
`docs/DEPLOY.md`.
