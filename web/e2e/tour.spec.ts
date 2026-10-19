import { expect, test, type Page } from '@playwright/test';

// Reduced motion makes the tour's fly-to moves instant (MapLibre jumps for non-essential moves).
// SwiftShader draws every frame on the CPU, so the map is small and the tests may run slowly.
test.use({ viewport: { width: 760, height: 520 }, reducedMotion: 'reduce' });
test.beforeEach(() => test.slow());

// What each step must do, written out here rather than read from the cards: the tour is
// supposed to match the spec, and the cards are what is being tested.
const STEPS = [
  { layer: 'net_toa', particles: 'off', arrows: 'off', view: [10, 15, 1.4] },
  { layer: 't_emit', particles: 'off', arrows: 'off', view: [10, 15, 1.4] },
  { layer: 'carnot', particles: 'off', arrows: 'off', view: [10, 15, 1.4] },
  { layer: 'j_ratio', particles: 'off', arrows: 'off', view: [15, 20, 2.2] },
  { layer: 'evap_frac', particles: 'off', arrows: 'off', view: [10, 15, 1.4] },
  { layer: 'diss_bl', particles: 'wind100', arrows: 'off', view: [-20, 30, 1.6] },
  { layer: 'precip', particles: 'off', arrows: 'off', view: [60, 5, 1.8] },
  { layer: 'div_e', particles: 'off', arrows: 'on', view: [-30, 35, 1.5] },
  { layer: 'net_toa', particles: 'wind10', arrows: 'off', view: [10, 15, 1.4] },
] as const;

async function open(page: Page, extra = '') {
  await page.goto(`/?particles=off&debug${extra}`);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

const body = (page: Page) => page.locator('body');

async function expectStep(page: Page, i: number) {
  const s = STEPS[i]!;
  await expect(body(page)).toHaveAttribute('data-tour', String(i + 1));
  await expect(body(page)).toHaveAttribute('data-layer', s.layer);
  await expect(body(page)).toHaveAttribute('data-particles', s.particles);
  await expect(body(page)).toHaveAttribute('data-arrows', s.arrows);
  await expect(body(page)).toHaveAttribute('data-anomaly', 'off');
  await expect.poll(() => page.evaluate(() => {
    const { map } = (window as unknown as { ehe: { map: { getCenter(): { lng: number; lat: number }; getZoom(): number } } }).ehe;
    const c = map.getCenter();
    return [c.lng, c.lat, map.getZoom()].map((v) => Math.round(v * 100) / 100);
  })).toEqual([...s.view]);
  await expect(page.locator('.tour-count')).toHaveText(`Step ${i + 1} of 9`);
}

test('the tour runs through all nine steps forwards and back, each setting layer, overlays and view', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await open(page);
  await expect(page.locator('#tour')).toBeHidden();
  await page.getByRole('button', { name: 'Take the tour' }).click();
  await expect(page.locator('#tour')).toBeVisible();
  await expectStep(page, 0);
  for (let i = 1; i < 9; i++) {
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expectStep(page, i);
  }
  await expect(page.getByRole('button', { name: 'Finish', exact: true })).toBeVisible();
  for (let i = 7; i >= 0; i--) {
    await page.getByRole('button', { name: 'Back', exact: true }).click();
    await expectStep(page, i);
  }
  await expect(page.getByRole('button', { name: 'Back', exact: true })).toBeDisabled();
  expect(errors).toEqual([]);
});

test('each card shows its title and its text', async ({ page }) => {
  await open(page, '&tour=4');
  await expect(page.locator('.tour-title')).toHaveText('The feedback');
  await expect(page.locator('.tour-body')).toContainText('over land only');
  await expect(page.locator('.tour-body strong')).toHaveText('land only');
});

test('the overlay controls follow the step, and the anomaly is switched off', async ({ page }) => {
  await open(page, '&anom=1');
  await expect(page.locator('.anomaly-on')).toBeChecked();
  await page.getByRole('button', { name: 'Take the tour' }).click();
  await expect(page.locator('.anomaly-on')).not.toBeChecked();
  await page.getByRole('button', { name: 'Step 6: Output' }).click();
  await expect(page.locator('.particles-on')).toBeChecked();
  await expect(page.locator('.particles-level')).toHaveValue('wind100');
  await expect(page.locator('.arrows-on')).not.toBeChecked();
  await page.getByRole('button', { name: 'Step 8: Transport' }).click();
  await expect(page.locator('.arrows-on')).toBeChecked();
  await expect(page.locator('.particles-on')).not.toBeChecked();
});

test('arrows point along the flux and the legend says how long a full arrow is', async ({ page }) => {
  await open(page, '&tour=8');
  await expect(body(page)).toHaveAttribute('data-arrows', 'on');
  await expect(page.locator('.legend-arrows')).toHaveText('Arrows: divergent energy transport; full length is 5.00 × 10⁸ W m⁻¹');
  await expect.poll(() => page.evaluate(() => (window as unknown as { ehe: { arrows: { lastInstances: Float32Array } } }).ehe.arrows.lastInstances.length)).toBeGreaterThan(40);
  const dirs = await page.evaluate(() => {
    const a = (window as unknown as { ehe: { arrows: { lastInstances: Float32Array } } }).ehe.arrows.lastInstances;
    return Array.from({ length: a.length / 4 }, (_, k) => [a[4 * k + 2]!, a[4 * k + 3]!]);
  });
  for (const [dx, dy] of dirs) {
    expect(dx).toBeGreaterThan(0); // the fixture flux is eastward
    expect(Math.abs(dy!)).toBeLessThan(0.01);
  }
  // Switching them off removes them from the screen and the legend.
  const clip = { x: 100, y: 120, width: 300, height: 250 };
  await page.mouse.move(0, 0);
  const withArrows = await page.screenshot({ clip });
  await page.locator('.arrows-on').uncheck();
  await expect(body(page)).toHaveAttribute('data-arrows', 'off');
  await expect(page.locator('.legend-arrows')).toBeHidden();
  await page.waitForTimeout(300);
  expect((await page.screenshot({ clip })).equals(withArrows)).toBe(false);
});

test('arrows work without the tour, and a date without them says so', async ({ page }) => {
  await open(page, '&arrows=1&date=2026-09-29');
  await expect(body(page)).toHaveAttribute('data-arrows', 'missing');
  await expect(page.locator('.legend-arrows')).toHaveText('No transport arrows for 2026-09-29');
  await page.getByRole('button', { name: 'Next day' }).click();
  await expect(body(page)).toHaveAttribute('data-arrows', 'on');
});

test('arrow keys on the card move between steps, and Escape closes the tour', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Take the tour' }).click();
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeFocused();
  await page.keyboard.press('ArrowRight');
  await expectStep(page, 1);
  await expect(body(page)).toHaveAttribute('data-date', '2026-10-01'); // the time bar did not move
  await page.keyboard.press('ArrowLeft');
  await expectStep(page, 0);
  await page.keyboard.press('Escape');
  await expect(page.locator('#tour')).toBeHidden();
  await expect(body(page)).not.toHaveAttribute('data-tour', /.*/);
  await expect(body(page)).toHaveAttribute('data-layer', 'net_toa'); // the map stays as the tour left it
});

test('the progress dots jump to a step, and Finish closes the tour', async ({ page }) => {
  await open(page, '&tour=1');
  await page.getByRole('button', { name: 'Step 5: The split' }).click();
  await expectStep(page, 4);
  await expect(page.getByRole('button', { name: 'Step 5: The split' })).toHaveAttribute('aria-current', 'step');
  await page.getByRole('button', { name: 'Step 9: Explore' }).click();
  await page.getByRole('button', { name: 'Finish', exact: true }).click();
  await expect(page.locator('#tour')).toBeHidden();
});

test('the readout moves below the card while the tour is open', async ({ page }) => {
  await open(page, '&tour=2&pin=0.25,-35.25');
  await expect(page.locator('#readout')).toBeVisible();
  const card = (await page.locator('#tour').boundingBox())!;
  const readout = (await page.locator('#readout').boundingBox())!;
  expect(readout.y).toBeGreaterThanOrEqual(card.y + card.height);
  await page.locator('.tour-close').click();
  await expect.poll(async () => (await page.locator('#readout').boundingBox())!.y).toBeLessThan(card.y + card.height);
});

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 800 } });

  test('the card sits above the legend and never runs off the screen', async ({ page }) => {
    await open(page);
    await page.locator('#menu-toggle').click();
    await page.getByRole('button', { name: 'Take the tour' }).click();
    await expect(page.locator('#tour')).toBeVisible();
    await expect(page.locator('#menu')).toBeHidden(); // the menu closes so it doesn't cover the card
    const card = (await page.locator('#tour').boundingBox())!;
    const legend = (await page.locator('#legend').boundingBox())!;
    expect(card.x).toBeGreaterThanOrEqual(0);
    expect(card.x + card.width).toBeLessThanOrEqual(390);
    expect(card.y + card.height).toBeLessThanOrEqual(legend.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});
