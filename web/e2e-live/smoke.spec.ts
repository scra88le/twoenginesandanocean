import { expect, test } from '@playwright/test';

// A smoke test of the live site: the page, the data it reads and the headers it is served with.
// It checks that things work, not that every layer looks right (the other suites do that).
//
//   SITE_URL        the deployed site (required)
//   MAX_AGE_DAYS    the newest date may be at most this many days old (default 14; ERA5 lags ~6)
//   MIN_DATES       at least this many published dates (default 1)
const MAX_AGE_DAYS = Number(process.env.MAX_AGE_DAYS ?? 14);
const MIN_DATES = Number(process.env.MIN_DATES ?? 1);

interface ManifestShape {
  dates: string[];
  built_layers: string[];
  built_at: string;
  points?: unknown;
}

test('the site loads its data and draws a map', async ({ page }) => {
  const errors: string[] = [];
  const failed: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('response', (r) => r.status() >= 400 && failed.push(`${r.status()} ${r.url()}`));
  const manifestResponse = page.waitForResponse((r) => /manifest\.json/.test(r.url()));
  // A fixed view of the open South Atlantic, where every deployment has point data.
  await page.goto('./?center=0.25,-35.25&zoom=4&particles=off');
  const res = await manifestResponse;
  expect(res.status()).toBe(200);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 60_000 });

  // The data is fresh and complete enough.
  const m = (await res.json()) as ManifestShape;
  expect(m.dates.length, 'published dates').toBeGreaterThanOrEqual(MIN_DATES);
  const newest = m.dates.at(-1)!;
  const age = (Date.now() - Date.parse(`${newest}T00:00:00Z`)) / 86_400_000;
  expect(age, `the newest date, ${newest}, is ${age.toFixed(1)} days old`).toBeLessThanOrEqual(MAX_AGE_DAYS);
  expect(m.built_layers.length).toBeGreaterThan(0);
  await expect(page.locator('body')).toHaveAttribute('data-date', newest);

  // The page shows what it should: the legend, the credit, the time bar on the newest date.
  await expect(page.locator('.legend-title')).not.toBeEmpty();
  await expect(page.locator('#credits')).toContainText('Copernicus Climate Change Service');
  await expect(page.locator('.tb-date')).toHaveText(newest);

  // The map really drew the data: the middle of the screen is not the background colour.
  const box = (await page.locator('#map canvas').boundingBox())!;
  const shot = await page.screenshot({ clip: { x: Math.round(box.x + box.width / 2), y: Math.round(box.y + box.height / 2), width: 1, height: 1 } });
  const { decodePng } = await import('../src/png');
  const px = (await decodePng(shot)).data;
  expect([px[0], px[1], px[2]]).not.toEqual([11, 14, 20]);

  // Point and series chunks are reachable (this fails if the bucket's CORS is wrong).
  if (m.points) {
    await page.mouse.click(Math.round(box.x + box.width / 2), Math.round(box.y + box.height / 2));
    await expect(page.locator('#readout')).toBeVisible();
    await expect(page.locator('body')).toHaveAttribute('data-readout', /.+/, { timeout: 30_000 });
    await expect(page.locator('body')).toHaveAttribute('data-chart', /:\d+/, { timeout: 30_000 });
  }
  expect(failed, 'requests that failed').toEqual([]);
  expect(errors, 'page errors').toEqual([]);
});

test('the manifest is never cached for long, so a new day shows up', async ({ page }) => {
  const manifestResponse = page.waitForResponse((r) => /manifest\.json/.test(r.url()));
  await page.goto('./');
  const cache = (await (await manifestResponse).allHeaders())['cache-control'] ?? '';
  const maxAge = /max-age=(\d+)/.exec(cache)?.[1];
  const ok = /no-cache|no-store/.test(cache) || (maxAge !== undefined && Number(maxAge) <= 300);
  expect(ok, `manifest.json is served with cache-control "${cache}"`).toBe(true);
});
