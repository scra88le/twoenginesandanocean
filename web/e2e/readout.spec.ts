import { expect, test, type Page } from '@playwright/test';

// Fixture point and series chunks exist only for the tiles around 0.25 E, 35.25 S (sea) and
// 35.25 N ("land"). t_emit there is 236 K on 2026-10-01 and 5 K less for each day before.
const VIEW = '/?layer=t_emit&center=0.25,-35.25&zoom=4&particles=off';

async function open(page: Page, extra = '') {
  await page.goto(VIEW + extra);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

const value = (page: Page, id: string) => page.locator(`#readout .ro-item[data-id="${id}"] .ro-value`);

test('clicking the map opens the local engine readout and chart within a second', async ({ page }) => {
  await open(page);
  const box = (await page.locator('#map canvas').boundingBox())!;
  const t0 = Date.now();
  await page.mouse.click(Math.round(box.x + box.width / 2), Math.round(box.y + box.height / 2));
  await expect(page.locator('#readout')).toBeVisible();
  await expect(page.locator('body')).toHaveAttribute('data-readout', /^18_12_200@2026-10-01$/);
  await expect(page.locator('body')).toHaveAttribute('data-chart', 't_emit:3:clim');
  expect(Date.now() - t0).toBeLessThan(1000);
  await expect(page.locator('.ro-place')).toHaveText('35.25° S, 0.25° E · 2026-10-01');
  await expect(page.locator('#readout th')).toHaveText([
    'Fuel', 'Hot side', 'Cold side', 'Ceiling', 'Max power', 'Actual', 'Split', 'Output', 'Water', 'Humans',
  ]);
  await expect(value(page, 't_emit')).toHaveText('236.00 K (−37.1 °C)');
  await expect(value(page, 't_skin')).toHaveText('300.00 K (26.9 °C)');
  await expect(value(page, 'j_opt')).toHaveText('—');
  await expect(value(page, 'j_opt')).toHaveAttribute('title', /^Ocean and sea ice/);
  await expect(value(page, 'human_q')).toHaveText('not available yet');
  await expect(page.locator('.ro-chart-title')).toHaveText('Temperature seen from space, T_e (K), 2026-09-29 to 2026-10-01');
  await expect(page.locator('.ro-chart canvas')).toHaveCount(1);
  await expect(page.locator('.pin')).toHaveCount(1);
});

test('the readout follows the date and the chart follows the layer', async ({ page }) => {
  await open(page, '&pin=0.25,-35.25');
  await expect(value(page, 't_emit')).toHaveText(/^236\.00 K/);
  await page.getByRole('button', { name: 'Previous day' }).click();
  await expect(value(page, 't_emit')).toHaveText(/^231\.00 K/);
  await expect(page.locator('.ro-place')).toHaveText(/2026-09-30$/);
  await page.locator('#menu input[value=net_toa]').check();
  await expect(page.locator('body')).toHaveAttribute('data-chart', 'net_toa:3:clim');
  await expect(page.locator('.ro-chart-title')).toHaveText(/^Net radiation, top of atmosphere \(W m⁻²\)/);
});

test('land cells show the max-power values', async ({ page }) => {
  await open(page, '&pin=0.25,35.25');
  await expect(value(page, 'j_opt')).toHaveText('100.00 W m⁻²');
  await expect(value(page, 'carnot')).toHaveText('15.00 %');
});

test('the close button and Escape close the readout and remove the pin', async ({ page }) => {
  await open(page, '&pin=0.25,-35.25');
  await expect(page.locator('#readout')).toBeVisible();
  await page.locator('.ro-close').click();
  await expect(page.locator('#readout')).toBeHidden();
  await expect(page.locator('.pin')).toHaveCount(0);
  await page.goto(VIEW + '&pin=0.25,-35.25');
  await expect(page.locator('#readout')).toBeVisible();
  await page.locator('.ro-close').focus();
  await page.keyboard.press('Escape');
  await expect(page.locator('#readout')).toBeHidden();
});

test('a cell without published chunks says so', async ({ page }) => {
  await open(page, '&pin=60.25,10.25');
  await expect(page.locator('.ro-message')).toHaveText('No point data for 2026-10-01.');
  await expect(page.locator('.ro-chart-note')).toHaveText('No 90-day series for Temperature seen from space, T_e yet.');
});

test('an energy-flow diagram above the table: sunlight in, heat out, the rest into the surface', async ({ page }) => {
  await open(page, '&pin=0.25,35.25');
  // fixture cell: 150 W m⁻² absorbed, latent 80, sensible 20, net into the surface 10, so infrared is 40
  const flow = page.locator('#readout .ro-flow');
  await expect(flow).toBeVisible();
  await expect(flow.locator('svg')).toHaveAttribute(
    'aria-label',
    'At the surface: sunlight absorbed 150 W m⁻². Heat leaving: latent 80 W m⁻², sensible 20 W m⁻², infrared 40 W m⁻². Net heat into the surface: 10 W m⁻².',
  );
  await expect(flow.locator('.ef-value')).toHaveText(['150 W m⁻²', '80 W m⁻²', '20 W m⁻²', '40 W m⁻²', '10 W m⁻²']);
  await expect(flow.locator('.ef-name').last()).toHaveText('Net in');
  // widths share one scale: the sunlight arrow is the widest, latent twice the sensible
  // the first line is the surface itself
  const w = (await flow.locator('line').evaluateAll((ls) => ls.map((l) => Number(l.getAttribute('stroke-width'))))).slice(1);
  expect(w[0]).toBe(Math.max(...w));
  expect(w[1]! / w[2]!).toBeCloseTo(4, 1);
  // it comes before the table, and goes with the readout
  const before = await page.evaluate(() => {
    const r = document.getElementById('readout')!;
    return !!(r.querySelector('.ro-flow')!.compareDocumentPosition(r.querySelector('.ro-table')!) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(before).toBe(true);
  await page.locator('.ro-close').click();
  await expect(flow).toBeHidden();
});

test('the diagram is hidden in Climate mode when the climate point chunk lacks its layers', async ({ page }) => {
  await open(page, '&mode=climate&frame=year&pin=0.25,35.25');
  await expect(value(page, 't_skin')).toBeVisible();
  await expect(page.locator('#readout .ro-flow')).toBeHidden(); // the fixture climatology has no lh and sh
});
