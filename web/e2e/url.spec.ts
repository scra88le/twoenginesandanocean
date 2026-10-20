import { expect, test, type Page } from '@playwright/test';

// SwiftShader draws on the CPU, so the map is small.
test.use({ viewport: { width: 760, height: 520 } });
test.beforeEach(() => test.slow()); // some tests load the page twice, and the workers share one CPU

const params = (page: Page) => new URL(page.url()).searchParams;

async function ready(page: Page) {
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

const mapView = (page: Page) =>
  page.evaluate(() => {
    const { map } = (window as unknown as { ehe: { map: { getCenter(): { lng: number; lat: number }; getZoom(): number } } }).ehe;
    const c = map.getCenter();
    return [c.lng, c.lat, map.getZoom()].map((v) => Math.round(v * 100) / 100);
  });

test('the address bar follows the app: layer, date, view, overlays, anomaly and pin', async ({ page }) => {
  await page.goto('/?particles=off&debug');
  await ready(page);
  await expect.poll(() => page.url()).toContain('layer=net_toa');
  expect(params(page).get('date')).toBe('2026-10-01');
  expect(params(page).get('particles')).toBe('off');
  expect(params(page).get('center')).toBe('0.25,20.00');
  expect(params(page).get('zoom')).toBe('1.40');
  expect(params(page).has('anom')).toBe(false);
  expect(params(page).has('debug')).toBe(true); // parameters the app doesn't own are kept

  await page.locator('#menu input[value=t_emit]').check();
  await expect.poll(() => params(page).get('layer')).toBe('t_emit');
  await page.getByRole('button', { name: 'Previous day' }).click();
  await expect.poll(() => params(page).get('date')).toBe('2026-09-30');
  await page.locator('.anomaly-on').check();
  await expect.poll(() => params(page).get('anom')).toBe('1');
  await page.locator('.arrows-on').check();
  await expect.poll(() => params(page).get('arrows')).toBe('1');
  await page.locator('.arrows-on').uncheck();
  await page.locator('.anomaly-on').uncheck();
  await expect.poll(() => params(page).has('anom') || params(page).has('arrows')).toBe(false);

  const box = (await page.locator('#map canvas').boundingBox())!;
  await page.mouse.move(box.x + 300, box.y + 250);
  await page.mouse.down();
  await page.mouse.move(box.x + 200, box.y + 230, { steps: 8 });
  await page.mouse.up();
  await expect.poll(() => params(page).get('center')).not.toBe('0.25,20.00');
  const [lng, lat, zoom] = await mapView(page);
  await expect.poll(() => params(page).get('center')).toBe(`${lng!.toFixed(2)},${lat!.toFixed(2)}`);
  expect(params(page).get('zoom')).toBe(zoom!.toFixed(2));

  await page.goto('/?layer=t_emit&center=0.25,-35.25&zoom=4&particles=off');
  await ready(page);
  const b2 = (await page.locator('#map canvas').boundingBox())!;
  await page.mouse.click(b2.x + b2.width / 2, b2.y + b2.height / 2);
  await expect.poll(() => params(page).get('pin')).toBe('0.25,-35.25');
  await page.locator('.ro-close').click();
  await expect.poll(() => params(page).has('pin')).toBe(false);
});

test('a copied URL restores layer, date, view, overlays, anomaly and the pinned point in a fresh page', async ({ page, browser }) => {
  await page.goto('/?layer=t_emit&date=2026-09-30&center=0.25,-35.25&zoom=4&particles=off&anom=1&arrows=1&pin=0.25,-35.25&debug');
  await ready(page);
  await expect(page.locator('body')).toHaveAttribute('data-readout', /^18_12_200@2026-09-30$/);
  // Wait for the app's own rewrite of the address bar (zoom gets two decimals): the URL the
  // visitor would copy, not the one that was typed.
  await expect.poll(() => page.url()).toContain('zoom=4.00');
  const copied = page.url();

  // A second, separate browser context (a different visitor). It must be closed: a worker's
  // browser is shared by the tests that follow, and a page left open keeps rendering.
  const context = await browser.newContext({ viewport: { width: 760, height: 520 } });
  const fresh = await context.newPage();
  await fresh.goto(copied);
  await ready(fresh);
  await expect(fresh.locator('body')).toHaveAttribute('data-layer', 't_emit');
  await expect(fresh.locator('body')).toHaveAttribute('data-date', '2026-09-30');
  await expect(fresh.locator('body')).toHaveAttribute('data-anomaly', 'on');
  await expect(fresh.locator('body')).toHaveAttribute('data-arrows', 'on');
  await expect(fresh.locator('body')).toHaveAttribute('data-particles', 'off');
  await expect(fresh.locator('.anomaly-on')).toBeChecked();
  await expect(fresh.locator('.arrows-on')).toBeChecked();
  expect(await mapView(fresh)).toEqual([0.25, -35.25, 4]);
  await expect(fresh.locator('#readout')).toBeVisible();
  await expect(fresh.locator('.ro-place')).toHaveText('35.25° S, 0.25° E · 2026-09-30');
  expect(new URL(fresh.url()).search).toBe(new URL(copied).search); // and it writes the same URL back
  await context.close();
});

test('replaceState keeps the Back button for leaving the site, not for every pan', async ({ page }) => {
  await page.goto('/?particles=off');
  await ready(page);
  const before = await page.evaluate(() => history.length);
  await page.locator('#menu input[value=t_emit]').check();
  await page.getByRole('button', { name: 'Previous day' }).click();
  await expect.poll(() => params(page).get('date')).toBe('2026-09-30');
  expect(await page.evaluate(() => history.length)).toBe(before);
});

test('a bad link falls back to defaults and is rewritten with valid values', async ({ page }) => {
  await page.goto('/?layer=bogus&date=1999-01-01&zoom=999&center=x,y&particles=wind50');
  await ready(page);
  await expect(page.locator('body')).toHaveAttribute('data-layer', 'net_toa');
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-10-01');
  await expect.poll(() => new URL(page.url()).search).toBe(
    '?layer=net_toa&date=2026-10-01&center=0.25,20.00&zoom=1.40&particles=wind10',
  );
});

test('?tour=N opens the tour once and is then dropped from the URL', async ({ page }) => {
  await page.goto('/?particles=off&tour=2');
  await ready(page);
  await expect(page.locator('body')).toHaveAttribute('data-tour', '2');
  await expect.poll(() => params(page).get('layer')).toBe('t_emit');
  expect(params(page).has('tour')).toBe(false);
});
