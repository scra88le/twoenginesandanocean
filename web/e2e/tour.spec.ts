import { expect, test, type Page } from '@playwright/test';

// Reduced motion makes the tour's fly-to moves instant (MapLibre jumps for non-essential moves).
// SwiftShader draws every frame on the CPU, so the map is small and the tests may run slowly.
test.use({ viewport: { width: 760, height: 520 }, reducedMotion: 'reduce' });
test.beforeEach(() => test.slow());

// What each step must do, written out here rather than read from the cards: the tour is
// supposed to match the spec, and the cards are what is being tested.
type Step = {
  title: string; chapter: string; layer: string; mode: 'climate' | 'today'; frame: string | null;
  particles: string; arrows: string; panel: boolean; view: readonly number[];
};
const S = (title: string, chapter: string, layer: string, over: Partial<Step> = {}, view: readonly number[] = [10, 15, 1.4]): Step => ({
  title, chapter, layer, mode: 'climate', frame: 'year', particles: 'off', arrows: 'off', panel: false, view, ...over,
});
const STEPS: Step[] = [
  S('Two engines and an ocean', 'Opening', 'net_toa'),
  S('Engine one: fuel', 'Engine one', 'asr_sfc'),
  S('The ceiling', 'Engine one', 'carnot'),
  S('Working at the limit', 'Engine one', 'j_ratio', {}, [15, 20, 2.2]),
  S('The split', 'Engine one', 'evap_frac'),
  S('Surplus and deficit', 'Engine two', 'net_toa', { panel: true }),
  S('Transport', 'Engine two', 'div_e', { arrows: 'on' }, [-30, 35, 1.5]),
  S('Output', 'Engine two', 'ke_col', { frame: '01', particles: 'jet250' }, [-30, 40, 1.6]),
  S('The ocean battery', 'The ocean', 'net_sfc', { frame: '07' }),
  S("The ocean's share", 'The ocean', 'net_sfc', { panel: true }, [-40, 35, 1.6]),
  S('The engine today', 'Today', 'ke_col', { mode: 'today', frame: null, particles: 'wind100' }),
  S('Explore', 'Today', 'net_toa'),
];
const N = STEPS.length;

async function open(page: Page, extra = '') {
  await page.goto(`/?particles=off&debug${extra}`);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

const body = (page: Page) => page.locator('body');
const dot = (page: Page, i: number) => page.getByRole('button', { name: new RegExp(`^Step ${i + 1}: ${STEPS[i]!.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) });

async function expectStep(page: Page, i: number) {
  const s = STEPS[i]!;
  await expect(body(page)).toHaveAttribute('data-tour', String(i + 1));
  await expect(body(page)).toHaveAttribute('data-layer', s.layer);
  await expect(body(page)).toHaveAttribute('data-mode', s.mode);
  if (s.frame) await expect(body(page)).toHaveAttribute('data-frame', s.frame);
  await expect(body(page)).toHaveAttribute('data-particles', s.particles);
  await expect(body(page)).toHaveAttribute('data-arrows', s.arrows);
  if (s.panel) await expect(page.locator('#zonal')).toBeVisible();
  else await expect(page.locator('#zonal')).toBeHidden();
  await expect(page.locator('.zb-open')).toHaveAttribute('aria-pressed', String(s.panel));
  await expect.poll(() => page.evaluate(() => {
    const { map } = (window as unknown as { ehe: { map: { getCenter(): { lng: number; lat: number }; getZoom(): number } } }).ehe;
    const c = map.getCenter();
    return [c.lng, c.lat, map.getZoom()].map((v) => Math.round(v * 100) / 100);
  })).toEqual([...s.view]);
  await expect(page.locator('.tour-count')).toHaveText(`Step ${i + 1} of ${N} · ${s.chapter}`);
  await expect(page.locator('.tour-title')).toHaveText(s.title);
}

test('the tour runs through all twelve steps forwards and back, each setting layer, mode, frame, overlays, panel and view', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await open(page);
  await expect(page.locator('#tour')).toBeHidden();
  await page.getByRole('button', { name: 'Take the tour' }).click();
  await expect(page.locator('#tour')).toBeVisible();
  await expectStep(page, 0);
  for (let i = 1; i < N; i++) {
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expectStep(page, i);
  }
  await expect(page.getByRole('button', { name: 'Finish', exact: true })).toBeVisible();
  for (let i = N - 2; i >= 0; i--) {
    await page.getByRole('button', { name: 'Back', exact: true }).click();
    await expectStep(page, i);
  }
  await expect(page.getByRole('button', { name: 'Back', exact: true })).toBeDisabled();
  expect(errors).toEqual([]);
});

test('each card shows its title and its text', async ({ page }) => {
  await open(page, '&tour=4');
  await expect(page.locator('.tour-title')).toHaveText('Working at the limit');
  await expect(page.locator('.tour-body')).toContainText('Kleidon and Renner');
  await expect(page.locator('.tour-body strong')).toHaveText('half the sunlight absorbed at the surface');
});

test('the progress dots break into chapters, and each dot names its chapter', async ({ page }) => {
  await open(page, '&tour=1');
  await expect(page.locator('.tour-dot')).toHaveCount(N);
  await expect(page.locator('.tour-dot.chapter-start')).toHaveCount(4); // Engine one, Engine two, The ocean, Today
  for (const i of [1, 5, 8, 10]) await expect(dot(page, i)).toHaveClass(/chapter-start/);
  for (const i of [0, 2, 3, 4, 6, 7, 9, 11]) await expect(dot(page, i)).not.toHaveClass(/chapter-start/);
  await expect(dot(page, 5)).toHaveAttribute('aria-label', 'Step 6: Surplus and deficit (Engine two)');
});

test('the controls follow the step: timescale, time bar, particle level, arrows and the zonal panel', async ({ page }) => {
  await open(page, '&mode=anom&layer=carnot');
  await expect(page.locator('.mode-anom')).toBeChecked();
  await page.getByRole('button', { name: 'Take the tour' }).click();
  await expect(page.locator('.mode-climate')).toBeChecked(); // the card's mode replaces Today vs normal
  await expect(page.locator('.legend-timescale')).toHaveText('Annual mean, 1991–2020');
  await expect(page.locator('.tb-year')).toHaveAttribute('aria-pressed', 'true');
  await dot(page, 7).click(); // Output: Climate, January, mean-flow particles at 250 hPa
  await expect(page.locator('.tb-date')).toHaveText('January');
  await expect(page.locator('.legend-timescale')).toHaveText('1991–2020 mean, January');
  await expect(page.locator('.particles-on')).toBeChecked();
  await expect(page.locator('.particles-level')).toHaveValue('jet250');
  await expect(page.locator('.legend-wind')).toHaveText('Particles: mean flow at 250 hPa, 1991–2020 January');
  await dot(page, 8).click(); // The ocean battery: July
  await expect(page.locator('.tb-date')).toHaveText('July');
  await expect(page.locator('.particles-on')).not.toBeChecked();
  await dot(page, 6).click(); // Transport: arrows
  await expect(page.locator('.arrows-on')).toBeChecked();
  await dot(page, 10).click(); // The engine today: Today, a date on the time bar, 100 m wind
  await expect(page.locator('.mode-today')).toBeChecked();
  await expect(page.locator('.tb-date')).toHaveText('2026-10-01');
  await expect(page.locator('.particles-level')).toHaveValue('wind100');
  await expect(page.locator('.legend-wind')).toHaveText('Particles: wind at 100 m (daily mean)');
  await expect(page.locator('.arrows-on')).not.toBeChecked();
});

test('the zonal panel opens on the steps that ask for it and closes on the others', async ({ page }) => {
  await open(page, '&tour=6');
  await expect(page.locator('#zonal')).toBeVisible();
  await expect(page.locator('#zonal .uplot')).toHaveCount(2);
  await expect(page).toHaveURL(/panel=zonal/);
  await expect(page.locator('#zonal .zb-twobox')).toContainText('Max-power prediction');
  const card = (await page.locator('#tour').boundingBox())!;
  const panel = (await page.locator('#zonal').boundingBox())!;
  expect(panel.x).toBeGreaterThanOrEqual(card.x + card.width); // beside the card, not under it
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.locator('#zonal')).toBeHidden();
  await expect(page).not.toHaveURL(/panel=zonal/);
  await dot(page, 9).click();
  await expect(page.locator('#zonal')).toBeVisible();
  await expect(page.locator('#zonal .zb-legend li')).toHaveCount(5); // Year frame: ocean transport too
});

test('the cards keep their place and the map stays as the tour leaves it, in Climate', async ({ page }) => {
  await open(page, '&tour=9');
  await expect(body(page)).toHaveAttribute('data-frame', '07');
  await page.locator('.tour-close').click();
  await expect(page.locator('#tour')).toBeHidden();
  await expect(body(page)).toHaveAttribute('data-layer', 'net_sfc');
  await expect(body(page)).toHaveAttribute('data-frame', '07');
  await expect(body(page)).toHaveAttribute('data-mode', 'climate');
});

test('arrows point along the flux and the legend says how long a full arrow is', async ({ page }) => {
  await open(page, '&tour=7');
  await expect(body(page)).toHaveAttribute('data-arrows', 'on');
  // Climate: the shared reference of the fixtures is 4e8; the daily one is the day's own
  await expect(page.locator('.legend-arrows')).toHaveText('Arrows: divergent energy transport, 1991–2020 annual mean; full length is 4.00 × 10⁸ W m⁻¹');
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
  await open(page, '&arrows=1&date=2026-09-29&mode=today');
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
  await dot(page, 4).click();
  await expectStep(page, 4);
  await expect(dot(page, 4)).toHaveAttribute('aria-current', 'step');
  await dot(page, 11).click();
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
