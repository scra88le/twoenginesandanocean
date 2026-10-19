import { expect, test } from '@playwright/test';
import { colourAt } from '../src/colormaps';
import { decodePng } from '../src/png';

// The fixture data root (pipeline/scripts/make_web_fixtures.py) has t_emit = 200 + 0.1 * i K,
// where i is the longitude column, so the cell centred on 0.25 E (i = 360) is 236 K.
const VIEW = '/?layer=t_emit&center=0.25,-30&zoom=4&particles=off'; // open South Atlantic: no coastline

test('renders the layer with legend, hover value and the right colour', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.goto(VIEW);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
  await expect(page.locator('.legend-title')).toHaveText('Effective emission temperature (K)');
  await expect(page.locator('#credits')).toContainText('Copernicus Climate Change Service');

  const box = (await page.locator('#map canvas').boundingBox())!;
  const cx = Math.round(box.x + box.width / 2);
  const cy = Math.round(box.y + box.height / 2);
  await page.mouse.move(cx, cy);
  await expect(page.locator('.legend-value')).toHaveText(/^236\.00 K \(−37\.\d °C\)$/);

  // The shader decodes 236 K and maps it onto the thermal scale (display 200-290 K), drawn at
  // 85% opacity over the #0b0e14 background.
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  const shot = await decodePng(await page.screenshot({ clip: { x: cx, y: cy, width: 1, height: 1 } }));
  const got = [...shot.data.subarray(0, 3)];
  const bg = [11, 14, 20];
  const want = colourAt('thermal', (236 - 200) / 90).map((c, k) => c * 0.85 + bg[k]! * 0.15);
  for (let k = 0; k < 3; k++) expect(Math.abs(got[k]! - want[k]!)).toBeLessThanOrEqual(3);
  expect(errors).toEqual([]);
});

test('shows a plain message when WebGL2 is missing', async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
      return type === 'webgl2' ? null : original.apply(this, [type, ...rest] as never);
    } as typeof original;
  });
  await page.goto(VIEW);
  await expect(page.locator('.fatal')).toHaveText(/needs WebGL2/);
});
