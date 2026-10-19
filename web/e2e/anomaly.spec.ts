import { expect, test, type Page } from '@playwright/test';
import { colourAt } from '../src/colormaps';
import { decodePng } from '../src/png';

// Fixture climatology: t_emit 230 K, net_toa 0, carnot 10% in every month. At the cell centred
// on 0.25 E, t_emit is 236 K on 2026-10-01, so its anomaly is +6 K (and +1 K on 09-30).
// t_emit's anomaly display range is +/-25 K on the balance scale (ANOMALY_DISPLAY).
const VIEW = '/?layer=t_emit&center=0.25,-30&zoom=4&particles=off';

async function open(page: Page, extra = '') {
  await page.goto(VIEW + extra);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

async function centre(page: Page) {
  const box = (await page.locator('#map canvas').boundingBox())!;
  return { x: Math.round(box.x + box.width / 2), y: Math.round(box.y + box.height / 2) };
}

test('the anomaly switch shows the difference from the monthly mean, centred on zero', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await open(page);
  await expect(page.locator('.anomaly-on')).toBeEnabled();
  await expect(page.locator('.anomaly-row')).toContainText('Anomaly vs 1991–2020');
  await page.locator('.anomaly-on').check();
  await expect(page.locator('body')).toHaveAttribute('data-anomaly', 'on');
  await expect(page.locator('.legend-title')).toHaveText('Effective emission temperature, anomaly (K)');
  await expect(page.locator('.note-extra')).toHaveText('Difference from the 1991–2020 October mean');
  const c = await centre(page);
  await page.mouse.move(c.x, c.y);
  await expect(page.locator('.legend-value')).toHaveText('+6.00 K');

  // +6 K on +/-25 K maps to 0.5 + 0.5 * 6 / 25 on the balance scale, at 85% opacity.
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  const shot = await decodePng(await page.screenshot({ clip: { x: c.x, y: c.y, width: 1, height: 1 } }));
  const bg = [11, 14, 20];
  const want = colourAt('balance', 0.5 + (0.5 * 6) / 25).map((v, k) => v * 0.85 + bg[k]! * 0.15);
  for (let k = 0; k < 3; k++) expect(Math.abs(shot.data[k]! - want[k]!)).toBeLessThanOrEqual(3);
  expect(errors).toEqual([]);
});

test('the anomaly follows the date and starts on with ?anom=1', async ({ page }) => {
  await open(page, '&anom=1');
  await expect(page.locator('.anomaly-on')).toBeChecked();
  await expect(page.locator('body')).toHaveAttribute('data-anomaly', 'on');
  await page.getByRole('button', { name: 'Previous day' }).click();
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-09-30');
  const c = await centre(page);
  await page.mouse.move(c.x, c.y);
  await expect(page.locator('.legend-value')).toHaveText('+1.00 K');
  await expect(page.locator('.note-extra')).toHaveText('Difference from the 1991–2020 September mean');
});

test('a layer without an anomaly shows its value and says why', async ({ page }) => {
  await open(page, '&anom=1');
  await page.locator('#menu input[value=wind10]').check();
  await expect(page.locator('body')).toHaveAttribute('data-anomaly', 'unavailable');
  await expect(page.locator('.anomaly-note')).toHaveText('Not for this layer');
  await expect(page.locator('.note-extra')).toHaveText('No anomaly for this layer (see its info): showing the value');
  await expect(page.locator('.legend-title')).toHaveText('Wind 10 m (m s⁻¹)');
  await page.locator('#menu input[value=t_emit]').check();
  await expect(page.locator('body')).toHaveAttribute('data-anomaly', 'on');
  await expect(page.locator('.anomaly-note')).toHaveText('');
});

test('the info panel explains how the anomaly is made', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'About Local Carnot limit' }).click();
  await expect(page.locator('#info')).toContainText('approximation');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'About Wind 10 m' }).click();
  await expect(page.locator('#info')).toContainText('No anomaly.');
});

test('the readout chart draws the climatology as a dashed line', async ({ page }) => {
  await open(page, '&pin=0.25,-35.25');
  await expect(page.locator('body')).toHaveAttribute('data-chart', 't_emit:3:clim');
  await expect(page.locator('.ro-chart-note')).toHaveText('Dashed: the 1991–2020 mean for each calendar month.');
  await page.locator('#menu input[value=wind10]').check();
  await expect(page.locator('body')).toHaveAttribute('data-chart', 'wind10:3');
  await expect(page.locator('.ro-chart-note')).toHaveText('No climatology for this layer (see its info).');
});
