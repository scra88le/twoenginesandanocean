import { expect, test, type Page } from '@playwright/test';

// Fixture climate vectors (same in every frame; wind10 reverses in July): wind10 a mean easterly
// of 4 m/s, jet250 a mean northerly of 20 m/s, flux_e 1e8 W m-1 eastward with a shared arrow
// reference of 4e8. Today has a 10 m/s westerly and a 5e8 flux, each at full length.
const VIEW = '/?layer=net_toa&center=0.25,-30&zoom=4&debug';

test.use({ viewport: { width: 760, height: 520 } });
test.beforeEach(() => test.slow());

async function open(page: Page, extra = '') {
  await page.goto(VIEW + extra);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

type Ehe = {
  particles: { readState(): Promise<Float32Array> };
  arrows: { lastInstances: Float32Array };
};

async function velocity(page: Page): Promise<{ vx: number; vy: number }> {
  return page.evaluate(async () => {
    const { particles } = (window as unknown as { ehe: Ehe }).ehe;
    const a = await particles.readState();
    const t0 = performance.now();
    await new Promise((r) => setTimeout(r, 500));
    const b = await particles.readState();
    const dt = (performance.now() - t0) / 1000;
    let sx = 0;
    let sy = 0;
    let n = 0;
    for (let k = 0; k < a.length; k += 5) {
      const dx = b[k]! - a[k]!;
      const dy = b[k + 1]! - a[k + 1]!;
      if (b[k + 4]! < a[k + 4]! && Math.hypot(dx, dy) < 0.01) {
        sx += dx;
        sy += dy;
        n++;
      }
    }
    return { vx: sx / n / dt, vy: sy / n / dt };
  });
}

/** Mean arrow length on screen (CSS px) and the number of arrows. */
async function arrowLength(page: Page): Promise<{ len: number; n: number }> {
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { ehe: Ehe }).ehe.arrows.lastInstances.length), {
      timeout: 15_000,
    })
    .toBeGreaterThan(40);
  return page.evaluate(() => {
    const a = (window as unknown as { ehe: Ehe }).ehe.arrows.lastInstances;
    const n = a.length / 4;
    let sum = 0;
    for (let k = 0; k < n; k++) sum += Math.hypot(a[4 * k + 2]!, a[4 * k + 3]!);
    return { len: sum / n, n };
  });
}

test('Climate particles show the mean flow of the frame and say so', async ({ page }) => {
  await open(page, '&mode=climate&frame=year&particles=wind10');
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'wind10');
  await expect(page.locator('.legend-wind')).toHaveText(
    'Particles: mean flow at 10 m, 1991–2020 annual mean',
  );
  expect((await velocity(page)).vx).toBeLessThan(0); // a mean easterly
  const box = (await page.locator('#map canvas').boundingBox())!;
  await page.mouse.move(Math.round(box.x + box.width / 2), Math.round(box.y + box.height / 2));
  await expect(page.locator('.legend-wind')).toHaveText('Mean wind 10 m: 4.0 m/s from E');
  // July's mean flow is reversed in the fixture: the frame changes the particles.
  await page.mouse.move(0, 0);
  await page.getByRole('button', { name: 'Previous month' }).click(); // Year -> December
  for (let k = 0; k < 5; k++) await page.getByRole('button', { name: 'Previous month' }).click();
  await expect(page.locator('body')).toHaveAttribute('data-frame', '07');
  await expect(page.locator('.legend-wind')).toHaveText('Particles: mean flow at 10 m, 1991–2020 July');
  expect((await velocity(page)).vx).toBeGreaterThan(0);
});

test('Climate mean flow at 250 hPa, and Today brings the daily wind back', async ({ page }) => {
  await open(page, '&mode=climate&frame=01&particles=jet250');
  await expect(page.locator('.legend-wind')).toHaveText('Particles: mean flow at 250 hPa, 1991–2020 January');
  expect((await velocity(page)).vy).toBeGreaterThan(0); // mean northerly: mercator y grows southwards
  await page.locator('.mode-today').check();
  await expect(page.locator('body')).toHaveAttribute('data-mode', 'today');
  await expect(page.locator('.legend-wind')).toHaveText('Particles: wind at 250 hPa (daily mean)');
  expect((await velocity(page)).vy).toBeLessThan(0); // the day's jet is a southerly
});

test('Climate arrows use the shared reference, so a weaker flux draws shorter', async ({ page }) => {
  await open(page, '&mode=climate&frame=year&arrows=1');
  await expect(page.locator('body')).toHaveAttribute('data-arrows', 'on');
  await expect(page.locator('.legend-arrows')).toHaveText(
    'Arrows: divergent energy transport, 1991–2020 annual mean; full length is 4.00 × 10⁸ W m⁻¹',
  );
  const climate = await arrowLength(page);
  await page.getByRole('button', { name: 'Previous month' }).click(); // December: same flux
  await expect(page.locator('body')).toHaveAttribute('data-frame', '12');
  await expect(page.locator('.legend-arrows')).toHaveText(
    'Arrows: divergent energy transport, 1991–2020 December; full length is 4.00 × 10⁸ W m⁻¹',
  );
  expect((await arrowLength(page)).len).toBeCloseTo(climate.len, 1);
  await page.locator('.mode-today').check();
  await expect(page.locator('.legend-arrows')).toHaveText(
    'Arrows: divergent energy transport; full length is 5.00 × 10⁸ W m⁻¹',
  );
  const today = await arrowLength(page);
  // 1e8 of a 4e8 reference against 5e8 of a 5e8 reference
  expect(climate.len / today.len).toBeCloseTo(0.25, 1);
});
