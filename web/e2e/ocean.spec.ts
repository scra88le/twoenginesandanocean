import { expect, test, type Page } from '@playwright/test';

// Fixture ocean (see pipeline/scripts/make_web_fixtures.py): water over 80 W - 0 E, 40 S - 75 N.
// The upper limb carries 220 m2/s north at 0.2 m/s, the deep limb 150 m2/s south at 0.05 m/s.
// 2026-10-01 has the daily field and the 30-day mean, 09-30 the daily field only, 09-29 none.
const VIEW = '/?layer=t_emit&mode=today&center=-40,20&zoom=2.5&particles=off';

test.use({ viewport: { width: 760, height: 520 } });
test.beforeEach(() => test.slow());

type Layer = { readState(): Promise<Float32Array> };
type Ehe = { ehe: { ocean: Record<'amoc_upper' | 'amoc_deep', Layer> } };

async function open(page: Page, extra = '') {
  await page.goto(VIEW + extra);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

/**
 * For one limb's layer: the mean velocity of the particles on the map (mercator units per
 * second, y south) and where they are, from two reads of the state a moment apart.
 */
async function sample(page: Page, limb: 'amoc_upper' | 'amoc_deep') {
  return page.evaluate(async (limb) => {
    const layer = (window as unknown as Ehe).ehe.ocean[limb];
    const a = await layer.readState();
    const t0 = performance.now();
    await new Promise((r) => setTimeout(r, 500));
    const b = await layer.readState();
    const dt = (performance.now() - t0) / 1000;
    let sx = 0;
    let sy = 0;
    let n = 0;
    let parked = 0;
    let lonMin = 180;
    let lonMax = -180;
    for (let k = 0; k < a.length; k += 5) {
      if (b[k + 1]! < 0) {
        parked++; // waiting above the map for a place with water
        continue;
      }
      const dx = b[k]! - a[k]!;
      const dy = b[k + 1]! - a[k + 1]!;
      if (a[k + 1]! >= 0 && b[k + 4]! < a[k + 4]! && Math.hypot(dx, dy) < 0.05) { // same particle: at most ~0.02 in 0.5 s here
        sx += dx;
        sy += dy;
        n++;
        const lon = (((b[k]! % 1) + 1) % 1) * 360 - 180;
        lonMin = Math.min(lonMin, lon);
        lonMax = Math.max(lonMax, lon);
      }
    }
    return { vx: sx / n / dt, vy: sy / n / dt, n, parked, lonMin, lonMax };
  }, limb);
}

test('the ocean overlay is off by default and its controls wait for it', async ({ page }) => {
  await open(page);
  await expect(page.locator('body')).toHaveAttribute('data-ocean', 'off');
  await expect(page.locator('.ocean-on')).not.toBeChecked();
  await expect(page.locator('.legend-ocean')).toBeHidden();
});

test('both limbs flow where the water is: the upper north, the deep south, slower', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await open(page, '&ocean=both&debug');
  await expect(page.locator('body')).toHaveAttribute('data-ocean', 'both');
  await expect(page.locator('.legend-ocean')).toHaveText(
    'Ocean overturning (GLO12, 30-day mean to 2026-10-01): across 26.5° N, upper limb 16.2 Sv north, ' +
      'deep limb 15.5 Sv south; AMOC 17.0 Sv at 1,154 m',
  );
  await expect(page.locator('.ocean-swatch')).toHaveCount(2);
  await page.waitForTimeout(1500);
  const up = await sample(page, 'amoc_upper');
  const deep = await sample(page, 'amoc_deep');
  expect(up.n).toBeGreaterThan(50);
  expect(up.vy).toBeLessThan(0); // north: mercator y grows southwards
  expect(Math.abs(up.vx)).toBeLessThan(-up.vy / 50);
  expect(deep.vy).toBeGreaterThan(0); // south
  // Screen speed is velocity / speed_hi: 0.2 / 0.3 against 0.05 / 0.05.
  expect(deep.vy / -up.vy).toBeCloseTo(1.5, 0);
  // Particles are drawn only where there is water (80 W to 0 E); the rest wait off the map.
  expect(up.lonMin).toBeGreaterThan(-81);
  expect(up.lonMax).toBeLessThan(1);
  expect(up.parked).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

test('hover reads both limbs, and the URL keeps the choice', async ({ page }) => {
  await open(page, '&ocean=upper&ocean_avg=daily');
  await expect(page.locator('body')).toHaveAttribute('data-ocean', 'upper');
  await expect(page.locator('.legend-ocean')).toContainText('daily mean, 2026-10-01');
  await expect(page.locator('.legend-ocean')).not.toContainText('deep limb');
  const box = (await page.locator('#map canvas').boundingBox())!;
  await page.mouse.move(Math.round(box.x + box.width / 2), Math.round(box.y + box.height / 2));
  await expect(page.locator('.legend-ocean')).toHaveText('Upper limb: 220 m²/s, 0.20 m/s toward N');
  await expect(page).toHaveURL(/ocean=upper&ocean_avg=daily/);
  await page.locator('.ocean-limbs').selectOption('both');
  await expect(page.locator('body')).toHaveAttribute('data-ocean', 'both');
  await page.mouse.move(Math.round(box.x + box.width / 2) + 1, Math.round(box.y + box.height / 2));
  await expect(page.locator('.legend-ocean')).toHaveText(
    'Upper limb: 220 m²/s, 0.20 m/s toward N; Deep limb: 150 m²/s, 0.050 m/s toward S',
  );
  await expect(page).toHaveURL(/ocean=both&ocean_avg=daily/);
});

test('a date without the mean falls back to daily, a date without currents says so', async ({ page }) => {
  await open(page, '&ocean=both&date=2026-09-30');
  await expect(page.locator('.legend-ocean')).toContainText('daily mean, 2026-09-30');
  await expect(page.locator('.legend-ocean')).toContainText('(30-day mean not available for this date)');
  await page.getByRole('button', { name: 'Previous day' }).click();
  await expect(page.locator('body')).toHaveAttribute('data-ocean', 'missing');
  await expect(page.locator('.legend-ocean')).toHaveText('No ocean currents for 2026-09-29 yet');
  await page.locator('.mode-climate').check();
  // Climate has no ocean normal: it draws the newest 30-day mean and says so.
  await expect(page.locator('body')).toHaveAttribute('data-ocean', 'both');
  await expect(page.locator('.legend-ocean')).toContainText('30-day mean to');
  await expect(page.locator('.legend-ocean')).toContainText('no 1991–2020 normal');
});

test('the info button explains the overlay', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'About the ocean overturning' }).click();
  await expect(page.locator('dialog#info[open] h2')).toHaveText('Ocean overturning (AMOC)');
  await expect(page.locator('dialog#info[open]')).toContainText('GLOBAL_ANALYSISFORECAST_PHY_001_024');
});

test('the AMOC panel draws the latitude-depth section and the trend, and closes with Escape', async ({ page }) => {
  await open(page);
  const button = page.getByRole('button', { name: 'AMOC section' });
  await button.click();
  await expect(page.locator('#amoc')).toBeVisible();
  await expect(page.locator('#amoc canvas.amoc-heat')).toHaveAttribute('aria-label', /30-day mean to 2026-10-01\. Strongest overturning: 18\.0 Sv at \d+\.\d° N, 1,100 m deep/);
  // The conveyor belt: the limbs by latitude, from the same file (the fixture's 18 Sv at 26.5 N).
  await expect(page.locator('#amoc canvas.amoc-belt')).toHaveAttribute('aria-label', /upper limb 1\d\.\d Sv north, deep limb 1\d\.\d Sv south/);
  const belt = await page.locator('#amoc canvas.amoc-belt').evaluate((c: HTMLCanvasElement) => {
    const at = (fx: number, fy: number) => Array.from(c.getContext('2d')!.getImageData(Math.round(c.width * fx), Math.round(c.height * fy), 1, 1).data);
    return { upper: at(0.6, 0.27), deep: at(0.6, 0.65) };
  });
  expect(belt.upper[0]!).toBeGreaterThan(belt.upper[2]!); // orange ribbon in the upper lane
  expect(belt.deep[2]!).toBeGreaterThan(belt.deep[0]!); // blue ribbon in the deep lane
  // The heat map is painted: a warm pixel at 30° N, 1100 m (the fixture's peak), a dark one at 70° S (no water).
  const warm = await page.locator('#amoc canvas.amoc-heat').evaluate((c: HTMLCanvasElement) => {
    const px = c.getContext('2d')!.getImageData(Math.round(c.width * 0.62), Math.round(c.height * 0.45), 1, 1).data;
    return px[0]! > px[2]!;
  });
  expect(warm).toBe(true);
  await expect(page.locator('#amoc .amoc-strength canvas, #amoc .amoc-strength .u-over')).not.toHaveCount(0);
  await expect(page.locator('#amoc .amoc-chart')).toBeVisible();
  await expect(page.locator('#amoc .zb-place')).toContainText('26.5° N');
  await page.locator('#amoc summary').first().click();
  await expect(page.locator('#amoc .amoc-heat-text')).toContainText('The equator');
  await page.locator('#amoc summary').last().click();
  await expect(page.locator('#amoc .amoc-trend-text')).toContainText('Daily AMOC strength on');
  await page.keyboard.press('Escape');
  await expect(page.locator('#amoc')).toBeHidden();
  await expect(button).toHaveAttribute('aria-pressed', 'false');
});
