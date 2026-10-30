import { expect, test, type Page } from '@playwright/test';

// Fixture zonal files: the global ASR of a frame is 240 + its index (July 246, Year 252); the
// daily files exist for 2026-09-30 (249) and 2026-10-01 (250) but not for 2026-09-29.
test.use({ viewport: { width: 1400, height: 800 } });
test.beforeEach(() => test.slow());

async function open(page: Page, query = '') {
  await page.goto(`/?layer=net_toa&particles=off${query}`);
  await expect(page.locator('body')).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

const strip = (page: Page, id: string) => page.locator(`#strip .es-item[data-id="${id}"]`);

test('the strip shows the Year frame, with the two-box item', async ({ page }) => {
  await open(page, '&mode=climate&frame=year');
  await expect(page.locator('#strip .es-head')).toHaveText('Global means · 1991–2020 annual mean');
  await expect(strip(page, 'asr').locator('.es-value')).toHaveText('252.0 W m⁻²');
  await expect(strip(page, 'twobox').locator('.es-value')).toHaveText('1.45 W m⁻²');
  await expect(strip(page, 'diss').locator('.es-value')).toContainText('2.00 W m⁻²');
  await expect(strip(page, 'asr')).toHaveAttribute('title', /Sunlight absorbed \(⟨ASR⟩\): /);
});

test('a month frame has no two-box item, and the strip follows the frame and the mode', async ({ page }) => {
  await open(page, '&mode=climate&frame=07');
  await expect(strip(page, 'asr').locator('.es-value')).toHaveText('246.0 W m⁻²');
  await expect(strip(page, 'twobox')).toHaveCount(0);
  await page.getByRole('button', { name: 'Next month' }).click();
  await expect(strip(page, 'asr').locator('.es-value')).toHaveText('247.0 W m⁻²');
  await page.locator('.mode-today').check();
  await expect(page.locator('#strip .es-head')).toHaveText('Global means · 2026-10-01');
  await expect(strip(page, 'asr').locator('.es-value')).toHaveText('250.0 W m⁻²');
  await expect(strip(page, 'twobox')).toHaveCount(0);
});

test('a date without a zonal file shows dashes in the strip and a message in the panel', async ({ page }) => {
  await open(page, '&mode=today&date=2026-09-29&panel=zonal');
  await expect(strip(page, 'asr').locator('.es-value')).toHaveText('—');
  await expect(page.locator('#zonal .zb-note')).toHaveText('No zonal budget is published for 2026-09-29 yet.');
  await expect(page.locator('#zonal .uplot')).toHaveCount(0);
});

test('the info button opens the layer panel and Esc returns focus to it', async ({ page }) => {
  await open(page, '&mode=climate&frame=year');
  const button = strip(page, 'carnot').locator('.es-info');
  await button.click();
  await expect(page.locator('dialog#info[open]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(button).toBeFocused();
});

test('the zonal budget panel opens from the menu, charts the Year frame and closes with Esc', async ({ page }) => {
  await open(page, '&mode=climate&frame=year');
  const toggle = page.getByRole('button', { name: 'Zonal budget', exact: true });
  await expect(page.locator('#zonal')).toBeHidden();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#zonal .uplot')).toHaveCount(2);
  await expect(page.locator('#zonal .zb-twobox')).toHaveText(
    'Max-power prediction: J ≈ 31 W m⁻², ΔT ≈ 29 K. ERA5: J = 41 W m⁻², ΔT = 21 K.',
  );
  await expect(page.locator('#zonal .zb-legend li')).toHaveCount(5); // the Year frame adds the ocean
  await expect(page).toHaveURL(/panel=zonal/);
  await page.locator('#zonal .zb-details summary').click();
  await expect(page.locator('#zonal .zb-summary li').first()).toContainText('Absorbed sunlight exceeds radiated heat between');
  // the panel has no canvas of its own to fail silently: both charts drew
  expect(await page.locator('#zonal canvas').count()).toBe(2);
  await page.locator('#zonal .zb-close').focus();
  await page.keyboard.press('Escape');
  await expect(page.locator('#zonal')).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(toggle).toBeFocused();
  await expect(page).not.toHaveURL(/panel=zonal/);
});

test('the panel follows the frame: no ocean line or two-box numbers in a month', async ({ page }) => {
  await open(page, '&mode=climate&frame=07&panel=zonal');
  await expect(page.locator('#zonal .uplot')).toHaveCount(2);
  await expect(page.locator('#zonal .zb-legend li')).toHaveCount(4);
  await expect(page.locator('#zonal .zb-twobox')).toContainText('annual mean');
  await expect(page.locator('#zonal .zb-place')).toHaveText('1991–2020 July');
  await page.getByRole('button', { name: 'Next month' }).click();
  await expect(page.locator('#zonal .zb-place')).toHaveText('1991–2020 August');
});

test('a copied URL restores the open panel', async ({ page, browser }) => {
  await open(page, '&mode=climate&frame=year');
  await page.getByRole('button', { name: 'Zonal budget', exact: true }).click();
  await expect(page).toHaveURL(/panel=zonal/);
  const fresh = await browser.newContext({ viewport: { width: 1400, height: 800 } });
  const again = await fresh.newPage();
  await again.goto(page.url());
  await expect(again.locator('#zonal .uplot')).toHaveCount(2);
  await expect(again.getByRole('button', { name: 'Zonal budget', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await fresh.close();
});

test('Today shows the day and a note that the two-box estimate is for the annual mean', async ({ page }) => {
  await open(page, '&mode=today&date=2026-09-30&panel=zonal');
  await expect(page.locator('#zonal .zb-place')).toHaveText('2026-09-30');
  await expect(page.locator('#zonal .zb-twobox')).toContainText('annual mean');
  await expect(strip(page, 'asr').locator('.es-value')).toHaveText('249.0 W m⁻²');
});
