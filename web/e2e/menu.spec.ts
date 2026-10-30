import { expect, test, type Page } from '@playwright/test';
import { decodePng } from '../src/png';

// Fixture data root: 15 layers are built (see make_web_fixtures.py); carnot = 15% north, 0 south.
const ready = (page: Page) =>
  expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });

test('menu lists all 25 layers in 5 groups, with unbuilt layers disabled', async ({ page }) => {
  await page.goto('/?layer=t_emit&particles=off');
  await ready(page);
  await expect(page.locator('#menu fieldset:not(.overlays):not(.mode-switch)')).toHaveCount(5);
  await expect(page.locator('#menu input[name=layer]')).toHaveCount(25);
  await expect(page.locator('#menu input[name=layer]:enabled')).toHaveCount(15); // the layers the fixtures build
  await expect(page.locator('#menu input[value=t_emit]')).toBeChecked();
  await expect(page.locator('#menu fieldset.overlays legend')).toHaveText('Overlays');
  await expect(page.locator('#menu fieldset.mode-switch legend')).toHaveText('Timescale');
  await expect(page.locator('#menu fieldset:not(.overlays):not(.mode-switch) legend').first()).toHaveText('Engine one: surface to sky');
  await expect(page.locator('#menu .group-blurb')).toHaveCount(5);
});

test('selecting a layer switches the raster and legend', async ({ page }) => {
  await page.goto('/?layer=t_emit&particles=off');
  await ready(page);
  await page.getByText('Net radiation, TOA', { exact: true }).click();
  await expect(page.locator('body')).toHaveAttribute('data-layer', 'net_toa');
  await expect(page.locator('.legend-title')).toHaveText('Net radiation, TOA (W m⁻²)');
});

test('arrow keys move through enabled layers', async ({ page }) => {
  await page.goto('/?layer=t_emit&particles=off');
  await ready(page);
  await page.locator('#menu input[value=net_toa]').focus();
  await page.keyboard.press('ArrowDown'); // div_e is the next built layer of Engine two
  await expect(page.locator('body')).toHaveAttribute('data-layer', 'div_e');
  await page.locator('#menu input[value=carnot]').check();
  await expect(page.locator('.legend-title')).toHaveText('Local Carnot limit (%)');
  await expect(page.locator('.note-hatch')).toHaveText('Hatched: clamped at zero');
});

test('info panel shows source, formula and caveats, and closes with Escape', async ({ page }) => {
  await page.goto('/?layer=t_emit&particles=off');
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
  await page.goto('/?layer=carnot&mode=today&center=-30,0&zoom=3&particles=off');
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
  await page.goto('/?layer=t_emit&particles=off');
  await ready(page);
  const toggle = page.getByRole('button', { name: 'Layers' });
  await expect(page.locator('#menu')).toBeHidden();
  await toggle.click();
  await expect(page.locator('#menu')).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
});

test('technical layers are under "More layers", closed unless the selected layer is in there', async ({ page }) => {
  await page.goto('/?layer=net_toa&particles=off');
  await ready(page);
  const more = page.locator('#menu details.more-layers');
  await expect(more).toHaveCount(3); // Engine one, Engine two and Water (p_lift)
  await expect(page.locator('#menu details.more-layers[open]')).toHaveCount(0);
  await expect(page.locator('#menu input[value=t_emit]')).toBeHidden();
  await expect(page.locator('#menu input[value=net_toa]')).toBeVisible();
  await page.locator('#menu details.more-layers summary').nth(1).click();
  await expect(page.locator('#menu input[value=t_emit]')).toBeVisible();
  await page.locator('#menu input[value=t_emit]').check();
  await expect(page.locator('body')).toHaveAttribute('data-layer', 't_emit');
});

test('opening on an advanced layer shows it in the menu', async ({ page }) => {
  await page.goto('/?layer=t_emit&particles=off');
  await ready(page);
  await expect(page.locator('#menu input[value=t_emit]')).toBeVisible();
  await expect(page.locator('#menu input[value=t_emit]')).toBeChecked();
  await expect(page.locator('#menu details.more-layers[open]')).toHaveCount(1);
});
