import { expect, test, type Page } from '@playwright/test';

// Fixture climatology (same every month and in the Year frame): t_emit 230 K, net_toa 0,
// carnot 10%, j_ratio 1. j_ratio is offered in Climate only.
async function open(page: Page, query: string) {
  await page.goto(`/?particles=off&center=0.25,-30&zoom=4&${query}`);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

const body = (page: Page) => page.locator('body');

test('a concept layer opens in Climate, Year frame, with the timescale in the legend', async ({ page }) => {
  await open(page, 'layer=net_toa');
  await expect(body(page)).toHaveAttribute('data-mode', 'climate');
  await expect(body(page)).toHaveAttribute('data-frame', 'year');
  await expect(page.locator('.mode-climate')).toBeChecked();
  await expect(page.locator('.legend-timescale')).toHaveText('Annual mean, 1991–2020');
  await expect(page.locator('.tb-year')).toBeVisible();
  await expect(page.locator('.tb-year')).toHaveAttribute('aria-pressed', 'true');
});

test('switching mode keeps the layer; Play cycles the months and loops', async ({ page }) => {
  await open(page, 'layer=t_emit&mode=today');
  await expect(page.locator('.tb-date')).toHaveText('2026-10-01');
  await page.locator('.mode-climate').check();
  await expect(body(page)).toHaveAttribute('data-layer', 't_emit');
  await expect(body(page)).toHaveAttribute('data-mode', 'climate');
  await expect(page.locator('.tb-date')).toHaveText('Annual mean');
  await page.getByRole('button', { name: 'Play' }).click();
  await expect(body(page)).toHaveAttribute('data-frame', '01'); // Year is skipped: it starts in January
  await expect(page.locator('.legend-timescale')).toHaveText('1991–2020 mean, January');
  await expect(body(page)).toHaveAttribute('data-frame', '02');
  await page.getByRole('button', { name: 'Pause' }).click();
  await page.locator('.mode-today').check();
  await expect(page.locator('.tb-date')).toHaveText('2026-10-01'); // back to the same day
  await expect(page.locator('.legend-timescale')).toHaveText('2026-10-01');
});

test('the Year button and the step buttons move between frames', async ({ page }) => {
  await open(page, 'layer=net_toa&frame=03');
  await expect(page.locator('.tb-date')).toHaveText('March');
  await page.getByRole('button', { name: 'Next month' }).click();
  await expect(body(page)).toHaveAttribute('data-frame', '04');
  await page.locator('.tb-year').click();
  await expect(body(page)).toHaveAttribute('data-frame', 'year');
  await page.getByRole('button', { name: 'Previous month' }).click();
  await expect(body(page)).toHaveAttribute('data-frame', '12');
});

test('selecting a Climate-only layer from Today switches the mode and says so', async ({ page }) => {
  await open(page, 'layer=t_emit&mode=today');
  await page.locator('#menu input[value=j_ratio]').check();
  await expect(body(page)).toHaveAttribute('data-layer', 'j_ratio');
  await expect(body(page)).toHaveAttribute('data-mode', 'climate');
  await expect(page.locator('.mode-today')).toBeDisabled();
  await expect(page.locator('.note-extra')).toHaveText(
    "Shown as the 1991–2020 average: daily values aren't meaningful for this layer.",
  );
  await expect(page.locator('.tb-year')).toBeVisible();
});

test('the readout in Climate mode shows the frame and a 12-month chart', async ({ page }) => {
  await open(page, 'layer=t_emit&mode=climate&frame=07&pin=0.25,-35.25');
  await expect(body(page)).toHaveAttribute('data-readout', '18_12_200@07');
  await expect(page.locator('.ro-place')).toHaveText('35.25° S, 0.25° E · July, 1991–2020');
  await expect(page.locator('.ro-item[data-id=t_skin] .ro-value')).toContainText('300');
  await expect(body(page)).toHaveAttribute('data-chart', 't_emit:climate');
  await expect(page.locator('.ro-chart-title')).toContainText('monthly means');
  await page.getByRole('button', { name: 'Next month' }).click();
  await expect(body(page)).toHaveAttribute('data-readout', '18_12_200@08');
});

test('a copied Climate URL restores mode and frame', async ({ page }) => {
  await open(page, 'layer=carnot&mode=climate&frame=11');
  await expect.poll(() => page.url()).toContain('mode=climate&frame=11');
  await expect(page.locator('.legend-timescale')).toHaveText('1991–2020 mean, November');
});
