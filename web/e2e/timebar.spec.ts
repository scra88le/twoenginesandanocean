import { expect, test, type Page } from '@playwright/test';

// Fixture dates: 2026-09-29, 09-30, 10-01. t_emit at the cell centred on 0.25 E is 236 K on
// the newest date and 5 K less for each day before.
const VIEW = '/?layer=t_emit&center=0.25,-30&zoom=4&particles=off'; // particles: see particles.spec.ts

async function open(page: Page) {
  await page.goto(VIEW);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

async function hoverCentre(page: Page) {
  const box = (await page.locator('#map canvas').boundingBox())!;
  await page.mouse.move(Math.round(box.x + box.width / 2), Math.round(box.y + box.height / 2));
}

const blur = (page: Page) => page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

test('starts on the newest date with the ERA5 lag note', async ({ page }) => {
  await open(page);
  await expect(page.locator('.tb-date')).toHaveText('2026-10-01');
  await expect(page.locator('#timebar')).toContainText('ERA5, about 6 days behind real time');
  await expect(page.locator('.tb-range')).toHaveAttribute('max', '2');
});

test('arrow keys step the date in under a second and the values follow', async ({ page }) => {
  await open(page);
  await hoverCentre(page);
  await expect(page.locator('.legend-value')).toHaveText(/^236\.00 K/);
  await blur(page);
  const t0 = Date.now();
  await page.keyboard.press('ArrowLeft');
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-09-30');
  expect(Date.now() - t0).toBeLessThan(1000);
  await hoverCentre(page);
  await expect(page.locator('.legend-value')).toHaveText(/^231\.00 K/);
  await blur(page);
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-10-01');
});

test('step buttons and the slider change the date', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Previous day' }).click();
  await page.getByRole('button', { name: 'Previous day' }).click();
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-09-29');
  await page.getByRole('button', { name: 'Previous day' }).click(); // already the oldest
  await expect(page.locator('.tb-date')).toHaveText('2026-09-29');
  await page.locator('.tb-range').focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-09-30');
  await expect(page.locator('.tb-range')).toHaveAttribute('aria-valuetext', '2026-09-30');
});

test('neighbouring days of the active layer and the particle level are pre-fetched', async ({ page }) => {
  const fetched = new Set<string>();
  page.on('request', (r) => {
    const m = r.url().match(/fields\/([\d-]+)\/(\w+)\.png/);
    if (m) fetched.add(`${m[1]}/${m[2]}`);
  });
  await page.goto(VIEW.replace('&particles=off', ''));
  await expect.poll(() => [...fetched].sort()).toEqual([
    '2026-09-29/t_emit', '2026-09-29/wind10_uv', // 09-29 has no wind; the miss is harmless
    '2026-09-30/t_emit', '2026-09-30/wind10_uv', '2026-10-01/t_emit', '2026-10-01/wind10_uv',
  ]);
});

test('play runs from the oldest to the newest date, then stops', async ({ page }) => {
  await open(page);
  const play = page.locator('.tb-play');
  await play.click();
  await expect(play).toHaveAttribute('aria-label', 'Pause');
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-09-29');
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-09-30', { timeout: 3000 });
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-10-01', { timeout: 3000 });
  await expect(play).toHaveAttribute('aria-label', 'Play');
});

test('switching layers keeps the date', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Previous day' }).click();
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-09-30');
  await page.locator('#menu').getByText('Net radiation, TOA', { exact: true }).click();
  await expect(page.locator('body')).toHaveAttribute('data-layer', 'net_toa');
  await expect(page.locator('body')).toHaveAttribute('data-date', '2026-09-30');
});
