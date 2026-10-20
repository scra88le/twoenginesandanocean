import { expect, test } from '@playwright/test';

// The production build served under /earth/ (port 5175, see playwright.config.ts), like a GitHub
// project Pages site. Everything it loads must be found relative to that path.
const SITE = 'http://localhost:5175/earth/';

test.use({ viewport: { width: 760, height: 520 } });

test('the site works from a sub-path: the map, the basemap, the data and the tour', async ({ page }) => {
  const bad: string[] = [];
  const errors: string[] = [];
  page.on('response', (r) => r.status() >= 400 && bad.push(`${r.status()} ${r.url()}`));
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`${SITE}?particles=off&debug&layer=t_emit`);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
  await expect(page.locator('.legend-title')).toHaveText('Effective emission temperature (K)');
  // The basemap (GeoJSON loaded in a worker) came from under /earth/, not from the site root.
  await expect.poll(() => page.evaluate(() => {
    const { map } = (window as unknown as { ehe: { map: { isSourceLoaded(id: string): boolean } } }).ehe;
    return map.isSourceLoaded('coastline') && map.isSourceLoaded('borders');
  })).toBe(true);
  // Every asset the page asked for was found.
  expect(bad).toEqual([]);
  expect(errors).toEqual([]);
  // And the app's own pieces still work.
  await page.getByRole('button', { name: 'Take the tour' }).click();
  await expect(page.locator('#tour')).toBeVisible();
});

test('the basemap files are requested under the sub-path', async ({ page }) => {
  const urls: string[] = [];
  page.on('request', (r) => r.url().includes('basemap') && urls.push(r.url()));
  await page.goto(`${SITE}?particles=off`);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
  await expect.poll(() => urls.length).toBeGreaterThanOrEqual(2);
  for (const u of urls) expect(u.startsWith('http://localhost:5175/earth/basemap/')).toBe(true);
});
