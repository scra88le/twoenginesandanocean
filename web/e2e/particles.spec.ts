import { expect, test, type Page } from '@playwright/test';

// Fixture winds: wind10 is a uniform 10 m/s westerly on 09-30 and 10-01 (none on 09-29), jet250
// a uniform 30 m/s southerly on 10-01, and wind100 isn't built.
const VIEW = '/?layer=t_emit&center=0.25,-30&zoom=4';

// SwiftShader draws every frame on the CPU; a smaller map keeps the animated tests quick.
test.use({ viewport: { width: 760, height: 520 } });
test.beforeEach(() => test.slow());

async function open(page: Page, extra = '') {
  await page.goto(VIEW + extra);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

async function hoverCentre(page: Page) {
  const box = (await page.locator('#map canvas').boundingBox())!;
  await page.mouse.move(Math.round(box.x + box.width / 2), Math.round(box.y + box.height / 2));
}

/** Two screenshots of the open ocean a moment apart: equal when nothing moves. */
async function frames(page: Page): Promise<[Buffer, Buffer]> {
  await page.mouse.move(0, 0);
  const clip = { x: 200, y: 200, width: 200, height: 150 };
  const a = await page.screenshot({ clip });
  await page.waitForTimeout(1200);
  return [a, await page.screenshot({ clip })];
}

test('particles are on by default at 10 m, animate, and say what they show', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await open(page);
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'wind10');
  await expect(page.locator('.particles-on')).toBeChecked();
  await expect(page.locator('.particles-level')).toHaveValue('wind10');
  await expect(page.locator('.legend-wind')).toHaveText('Particles: wind at 10 m (daily mean)');
  await page.waitForTimeout(1000);
  const [a, b] = await frames(page);
  expect(a.equals(b)).toBe(false);
  expect(errors).toEqual([]);
});

/**
 * Mean particle velocity on screen, in mercator units per second (x east, y south), from
 * two reads of the particle state. Particles that respawned in between are left out.
 */
async function velocity(page: Page): Promise<{ vx: number; vy: number; n: number }> {
  return page.evaluate(async () => {
    const { particles } = (window as unknown as { ehe: { particles: { readState(): Promise<Float32Array> } } }).ehe;
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
      if (b[k + 4]! < a[k + 4]! && Math.hypot(dx, dy) < 0.01) { // still the same particle
        sx += dx;
        sy += dy;
        n++;
      }
    }
    return { vx: sx / n / dt, vy: sy / n / dt, n };
  });
}

test('particles move with the wind: east in a westerly, north in a southerly', async ({ page }) => {
  await open(page, '&debug');
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'wind10');
  const east = await velocity(page);
  expect(east.n).toBeGreaterThan(100);
  expect(east.vx).toBeGreaterThan(0);
  expect(Math.abs(east.vy)).toBeLessThan(east.vx / 100);
  await page.locator('.particles-level').selectOption('jet250');
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'jet250');
  const north = await velocity(page);
  expect(north.vy).toBeLessThan(0); // mercator y grows southwards
  expect(Math.abs(north.vx)).toBeLessThan(-north.vy / 100);
});

test('hover shows the wind speed and direction as text', async ({ page }) => {
  await open(page);
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'wind10');
  await hoverCentre(page);
  await expect(page.locator('.legend-wind')).toHaveText('Wind 10 m: 10.0 m/s from W');
  await expect(page.locator('.legend-value')).toHaveText(/^236\.00 K/); // the raster still reads out
});

test('the level selector switches level; unbuilt levels are disabled', async ({ page }) => {
  await open(page);
  await expect(page.locator('.particles-level option[value="wind100"]')).toBeDisabled();
  await page.locator('.particles-level').selectOption('jet250');
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'jet250');
  await hoverCentre(page);
  await expect(page.locator('.legend-wind')).toHaveText('Wind 250 hPa: 30.0 m/s from S');
});

test('switching particles off stops the animation and hides the wind line', async ({ page }) => {
  await open(page);
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'wind10');
  await page.locator('.particles-on').uncheck();
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'off');
  await expect(page.locator('.legend-wind')).toBeHidden();
  const [a, b] = await frames(page);
  expect(a.equals(b)).toBe(true);
});

test('a date without wind says so, and the particles come back on the next date', async ({ page }) => {
  await open(page, '&date=2026-09-29');
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'missing');
  await expect(page.locator('.legend-wind')).toHaveText('No 10 m wind for 2026-09-29');
  await page.getByRole('button', { name: 'Next day' }).click();
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'wind10');
  await expect(page.locator('.legend-wind')).toHaveText('Particles: wind at 10 m (daily mean)');
});

test('?particles=jet250 picks the level and ?particles=off starts with them off', async ({ page }) => {
  await open(page, '&particles=jet250');
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'jet250');
  await open(page, '&particles=off');
  await expect(page.locator('body')).toHaveAttribute('data-particles', 'off');
  await expect(page.locator('.particles-on')).not.toBeChecked();
});
