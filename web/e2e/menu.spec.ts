import { expect, test, type Page } from '@playwright/test';
import { decodePng } from '../src/png';

// Fixture data root: only t_emit, net_toa and carnot are built (carnot = 15% north, 0 south).
const ready = (page: Page) =>
  expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });

test('menu lists all 24 layers in 9 groups, with unbuilt layers disabled', async ({ page }) => {
  await page.goto('/?layer=t_emit');
  await ready(page);
  await expect(page.locator('#menu fieldset')).toHaveCount(9);
  await expect(page.locator('#menu input[type=radio]')).toHaveCount(24);
  await expect(page.locator('#menu input[type=radio]:enabled')).toHaveCount(3);
  await expect(page.locator('#menu input[value=t_emit]')).toBeChecked();
  await expect(page.locator('#menu fieldset legend').first()).toHaveText('1 · Fuel');
});

test('selecting a layer switches the raster and legend', async ({ page }) => {
  await page.goto('/?layer=t_emit');
  await ready(page);
  await page.getByText('Net radiation, TOA', { exact: true }).click();
  await expect(page.locator('body')).toHaveAttribute('data-layer', 'net_toa');
  await expect(page.locator('.legend-title')).toHaveText('Net radiation, TOA (W m⁻²)');
});

test('arrow keys move through enabled layers', async ({ page }) => {
  await page.goto('/?layer=t_emit');
  await ready(page);
  await page.locator('#menu input[value=t_emit]').focus();
  await page.keyboard.press('ArrowDown'); // skips nothing disabled between t_emit and carnot
  await expect(page.locator('body')).toHaveAttribute('data-layer', 'carnot');
  await expect(page.locator('.legend-title')).toHaveText('Local Carnot limit (%)');
  await expect(page.locator('.note-hatch')).toHaveText('Hatched: clamped at zero');
});

test('info panel shows source, formula and caveats, and closes with Escape', async ({ page }) => {
  await page.goto('/?layer=t_emit');
  await ready(page);
  const button = page.getByRole('button', { name: 'About Maximum convective power' });
  await button.click();
  const dialog = page.locator('dialog#info');
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('h2')).toHaveText('Maximum convective power');
  await expect(dialog).toContainText('Kleidon & Renner (2013)');
  await expect(dialog).toContainText('G_max = R_s² / (4 k_r T_s)');
  await expect(dialog.locator('dt')).toContainText(['Source', 'Units', 'Sign convention', 'Formula']);
  await expect(dialog).toContainText('Copernicus Climate Change Service');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(button).toBeFocused();
});

async function distinctColours(page: Page, x: number, y: number): Promise<number> {
  const png = await decodePng(await page.screenshot({ clip: { x, y, width: 8, height: 8 } }));
  const seen = new Set<string>();
  for (let k = 0; k < png.data.length; k += png.channels) seen.add(png.data.subarray(k, k + 3).join(','));
  return seen.size;
}

test('carnot cells clamped at zero are hatched, others are not', async ({ page }) => {
  // Open ocean at 30 S (clamped) and 30 N (15%), away from coastlines.
  await page.goto('/?layer=carnot&center=-30,0&zoom=3');
  await ready(page);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  const box = (await page.locator('#map canvas').boundingBox())!;
  const cx = Math.round(box.x + box.width / 2) - 4;
  expect(await distinctColours(page, cx, Math.round(box.y + box.height * 0.8))).toBeGreaterThanOrEqual(2);
  expect(await distinctColours(page, cx, Math.round(box.y + box.height * 0.2))).toBe(1);
});

test('on a narrow screen the menu is behind a Layers button', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 760 });
  await page.goto('/?layer=t_emit');
  await ready(page);
  const toggle = page.getByRole('button', { name: 'Layers' });
  await expect(page.locator('#menu')).toBeHidden();
  await toggle.click();
  await expect(page.locator('#menu')).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
});
