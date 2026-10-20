import { expect, test, type Page } from '@playwright/test';

// A phone: 390 x 800, touch, and a mobile browser (which turns on the phone layout under 700 px).
test.use({ viewport: { width: 390, height: 800 }, isMobile: true, hasTouch: true });
test.beforeEach(() => test.slow());

async function open(page: Page, extra = '') {
  await page.goto(`/?layer=t_emit&center=0.25,-35.25&zoom=4&particles=off&debug${extra}`);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

const noSideScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

test('the layer menu is a bottom sheet over the lower part of the map', async ({ page }) => {
  await open(page);
  await expect(page.locator('#menu')).toBeHidden();
  await page.getByRole('button', { name: 'Layers' }).tap();
  const sheet = (await page.locator('#menu').boundingBox())!;
  expect(sheet.x).toBe(0);
  expect(sheet.width).toBe(390);
  expect(sheet.y + sheet.height).toBe(800); // flush with the bottom edge
  expect(sheet.height).toBeLessThanOrEqual(0.74 * 800 + 1);
  expect(sheet.y).toBeGreaterThan(150); // the map stays visible above it
  expect(await noSideScroll(page)).toBe(true);
  // Choosing a layer works from the sheet and leaves it open.
  await page.locator('#menu label:has(input[value=net_toa])').tap();
  await expect(page.locator('body')).toHaveAttribute('data-layer', 'net_toa');
  await expect(page.locator('#menu')).toBeVisible();
});

test('the sheet closes with Done, with Escape, and with a tap on the map', async ({ page }) => {
  await open(page);
  const toggle = page.getByRole('button', { name: 'Layers' });
  await toggle.tap();
  await page.getByRole('button', { name: 'Done' }).tap();
  await expect(page.locator('#menu')).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toBeFocused();
  await toggle.tap();
  await page.keyboard.press('Escape');
  await expect(page.locator('#menu')).toBeHidden();
  await toggle.tap();
  await page.touchscreen.tap(195, 120); // the map above the sheet
  await expect(page.locator('#menu')).toBeHidden();
});

test('Done is not shown on a desktop-sized screen', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 700 });
  await open(page);
  await expect(page.locator('#menu')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Done' })).toBeHidden();
});

test('touch targets are about 40 px, and the small info button has a larger tap area', async ({ page }) => {
  await open(page);
  const size = async (sel: string) => (await page.locator(sel).first().boundingBox())!;
  for (const sel of ['.tb-step', '.tb-play', '#menu-toggle']) {
    const b = await size(sel);
    expect(b.width, sel).toBeGreaterThanOrEqual(40);
    expect(b.height, sel).toBeGreaterThanOrEqual(40);
  }
  await page.getByRole('button', { name: 'Layers' }).tap();
  for (const sel of ['.menu-close', '.tour-start', '.particles-level']) {
    expect((await size(sel)).height, sel).toBeGreaterThanOrEqual(32);
  }
  // A tap 9 px outside the 22 px circle still opens the panel.
  const info = (await page.getByRole('button', { name: 'About Net radiation, TOA' }).boundingBox())!;
  await page.touchscreen.tap(info.x - 9, info.y - 9);
  await expect(page.locator('#info')).toBeVisible();
});

test('the readout is a full-height sheet with a big close button', async ({ page }) => {
  await open(page, '&pin=0.25,-35.25');
  await expect(page.locator('#readout')).toBeVisible();
  const r = (await page.locator('#readout').boundingBox())!;
  expect([r.x, r.y, r.width, r.height]).toEqual([0, 0, 390, 800]);
  const close = (await page.locator('.ro-close').boundingBox())!;
  expect(close.width).toBeGreaterThanOrEqual(40);
  expect(close.height).toBeGreaterThanOrEqual(40);
  expect(await noSideScroll(page)).toBe(true);
  await page.locator('.ro-close').tap();
  await expect(page.locator('#readout')).toBeHidden();
});

test('the tour card fits beside the Layers button and the menu closes when it starts', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Layers' }).tap();
  await page.getByRole('button', { name: 'Take the tour' }).tap();
  await expect(page.locator('#menu')).toBeHidden();
  const card = (await page.locator('#tour').boundingBox())!;
  const toggle = (await page.locator('#menu-toggle').boundingBox())!;
  expect(card.x + card.width).toBeLessThanOrEqual(toggle.x);
  expect(await noSideScroll(page)).toBe(true);
});

test('there are half as many wind particles per pixel as on a desktop', async ({ page, browser }) => {
  await page.goto('/?layer=t_emit&debug');
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
  const total = (p: Page) =>
    p.evaluate(() => (window as unknown as { ehe: { particles: { particleTotal: number } } }).ehe.particles.particleTotal);
  const phone = await total(page);
  expect(phone).toBe(Math.round((390 * 800) / 90 / 2));
  // A desktop-sized visitor, in a context that is closed afterwards: a worker's browser is
  // shared by later tests, and a page left open (with particles running) keeps rendering.
  const context = await browser.newContext({ viewport: { width: 760, height: 520 } });
  const desktop = await context.newPage();
  await desktop.goto('/?layer=t_emit&debug');
  await expect(desktop.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
  const d = await total(desktop);
  await context.close();
  expect(d).toBe(Math.round((760 * 520) / 90));
  expect(phone / (390 * 800)).toBeCloseTo(d / (760 * 520) / 2, 4);
});
