import { expect, test, type Page } from '@playwright/test';

// The overview infographic (docs/PROPOSALS-v2.md F13): the first thing a new visitor sees, and
// a way into the tour. The default Playwright context is a returning visitor (see the config);
// the first-visit tests clear that. SwiftShader draws every frame on the CPU, so allow time.
test.beforeEach(() => test.slow());

const dialog = (page: Page) => page.locator('#overview');
const body = (page: Page) => page.locator('body');

async function ready(page: Page) {
  await expect(body(page)).toHaveAttribute('data-ready', 'true', { timeout: 20_000 });
}

test.describe('first visit', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('a fresh visitor sees the overview with numbers from the annual mean, over a map that keeps loading', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('/?particles=off');
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page).getByRole('heading', { name: 'How the engine works' })).toBeVisible();
    // the fixture's annual mean: 252 W m⁻² absorbed, 5.4 PW by the air, 2.1 PW by the ocean
    await expect(dialog(page).locator('[data-slot=asr_toa]')).toHaveText('≈ 252 W m⁻²');
    await expect(dialog(page).locator('[data-slot=pw_atm]')).toHaveText('up to 5.4 PW');
    await expect(dialog(page).locator('[data-slot=pw_ocean]')).toHaveText('up to 2.1 PW');
    await expect(dialog(page).locator('[data-slot=t_r]')).toHaveText('256 K (−17 °C)');
    await expect(dialog(page).locator('[data-slot]', { hasText: '—' })).toHaveCount(0);
    await expect(dialog(page).locator('.ov-note')).toContainText('ERA5, 1991–2020 annual mean');
    await ready(page); // the map finished behind the dialog
    expect(errors).toEqual([]);
  });

  test('Explore the map closes it, and a reload does not show it again', async ({ page }) => {
    await page.goto('/?particles=off');
    await dialog(page).getByRole('button', { name: 'Explore the map' }).click();
    await expect(dialog(page)).toBeHidden();
    await ready(page);
    await page.reload();
    await ready(page);
    await expect(dialog(page)).toBeHidden();
  });

  test('Esc closes it and puts focus on the map; the next visit starts without it', async ({ page }) => {
    await page.goto('/?particles=off');
    await expect(dialog(page)).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog(page)).toBeHidden();
    await expect(page.locator('.maplibregl-canvas')).toBeFocused();
    await page.reload();
    await ready(page);
    await expect(dialog(page)).toBeHidden();
  });

  test('Take the tour closes it and opens step 1', async ({ page }) => {
    await page.goto('/?particles=off');
    await dialog(page).getByRole('button', { name: 'Take the tour' }).click();
    await expect(dialog(page)).toBeHidden();
    await expect(body(page)).toHaveAttribute('data-tour', '1');
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeFocused();
  });

  test('a link with a tour step goes to the tour and not the overview; ?overview=0 skips it too', async ({ page }) => {
    await page.goto('/?particles=off&tour=3');
    await ready(page);
    await expect(dialog(page)).toBeHidden();
    await expect(body(page)).toHaveAttribute('data-tour', '3');
    await page.goto('/?particles=off&overview=0');
    await ready(page);
    await expect(dialog(page)).toBeHidden();
  });

  test('a deep link still shows the overview first and keeps its state once it is closed', async ({ page }) => {
    await page.goto('/?layer=t_emit&date=2026-10-01&particles=off&debug');
    await expect(dialog(page)).toBeVisible();
    await dialog(page).getByRole('button', { name: 'Explore the map' }).click();
    await ready(page);
    await expect(body(page)).toHaveAttribute('data-layer', 't_emit');
  });
});

test.describe('returning visitor', () => {
  test('does not see it by itself; the menu button opens it, and Esc returns focus to that button', async ({ page }) => {
    await page.goto('/?particles=off');
    await ready(page);
    await expect(dialog(page)).toBeHidden();
    const button = page.getByRole('button', { name: 'How the engine works' });
    await button.click();
    await expect(dialog(page)).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog(page)).toBeHidden();
    await expect(button).toBeFocused();
  });

  test('?overview=1 opens it for a visitor who has seen it, and is dropped from the address', async ({ page }) => {
    await page.goto('/?particles=off&overview=1');
    await expect(dialog(page)).toBeVisible();
    await dialog(page).getByRole('button', { name: 'Explore the map' }).click();
    await ready(page);
    await expect.poll(() => page.url()).not.toContain('overview');
  });

  test('the ocean-transport element opens tour step 10: net_sfc, Climate, Year, zonal panel open', async ({ page }) => {
    await page.goto('/?particles=off&overview=1&debug');
    const link = dialog(page).getByRole('link', { name: /Heat carried poleward by the ocean/ });
    await expect(link).toHaveAccessibleName('Heat carried poleward by the ocean, up to 2.1 PW: open tour step 10');
    await link.click();
    await expect(dialog(page)).toBeHidden();
    await expect(body(page)).toHaveAttribute('data-tour', '10');
    await expect(body(page)).toHaveAttribute('data-layer', 'net_sfc');
    await expect(body(page)).toHaveAttribute('data-mode', 'climate');
    await expect(body(page)).toHaveAttribute('data-frame', 'year');
    await expect(page.locator('#zonal')).toBeVisible();
    await expect(page.locator('.tour-title')).toHaveText("The ocean's share");
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeFocused();
  });

  test('every element opens its own step, from the keyboard too', async ({ page }) => {
    const want: Record<string, [string, string]> = {
      toa: ['1', 'net_toa'], 'surface-sun': ['2', 'asr_sfc'], ceiling: ['3', 'carnot'], convection: ['4', 'j_ratio'],
      split: ['5', 'evap_frac'], surplus: ['6', 'net_toa'], 'air-transport': ['7', 'div_e'], friction: ['8', 'ke_col'],
      'ocean-store': ['9', 'net_sfc'], 'ocean-transport': ['10', 'net_sfc'],
    };
    await page.goto('/?particles=off&debug');
    await ready(page);
    for (const [el, [step, layer]] of Object.entries(want)) {
      await page.getByRole('button', { name: 'How the engine works' }).click();
      await dialog(page).locator(`[data-el=${el}]`).focus();
      await page.keyboard.press('Enter');
      await expect(dialog(page)).toBeHidden();
      await expect(body(page)).toHaveAttribute('data-tour', step);
      await expect(body(page)).toHaveAttribute('data-layer', layer);
    }
  });

  test('the chips highlight one part and dim the rest, with an explanation, never by colour alone', async ({ page }) => {
    await page.goto('/?particles=off&overview=1');
    const svg = dialog(page).locator('svg.ov-svg');
    await expect(svg).toHaveAttribute('data-focus', 'all');
    await dialog(page).getByRole('button', { name: 'Engine two' }).click();
    await expect(svg).toHaveAttribute('data-focus', 'engine2');
    await expect(dialog(page).getByRole('button', { name: 'Engine two' })).toHaveAttribute('aria-pressed', 'true');
    await expect(dialog(page).getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'false');
    await expect(dialog(page).locator('.ov-explain')).toContainText('carries the difference poleward');
    await expect(dialog(page).locator('[data-el=ceiling]')).toHaveCSS('opacity', '0.3');
    await expect(dialog(page).locator('[data-el=air-transport]')).toHaveCSS('opacity', '1');
    await expect(dialog(page).locator('[data-el=air-transport] .ov-hit')).toHaveCSS('stroke-width', '1.5px');
  });

  test('Read as text lists the same ten elements with their values and links, and swaps back', async ({ page }) => {
    await page.goto('/?particles=off&overview=1');
    await dialog(page).getByRole('button', { name: 'Read as text' }).click();
    await expect(dialog(page).locator('svg.ov-svg')).toBeHidden();
    const items = dialog(page).locator('.ov-list li');
    await expect(items).toHaveCount(10);
    await expect(items.nth(0)).toContainText('Sunlight absorbed and heat radiated to space');
    await expect(items.nth(5)).toContainText('Tropical surplus and high-latitude deficit'); // tour order, not drawing order
    await expect(items.nth(0)).toContainText('Sunlight absorbed: ≈ 252 W m⁻²');
    await expect(items.nth(9)).toContainText('Heat carried poleward by the ocean: up to 2.1 PW');
    await expect(dialog(page).getByRole('button', { name: 'Show the graphic' })).toHaveAttribute('aria-pressed', 'true');
    // the list's links lead to the same steps
    await items.nth(2).getByRole('button').click();
    await expect(dialog(page)).toBeHidden();
    await expect(body(page)).toHaveAttribute('data-tour', '3');
  });

  test('hovering text and tooltips carry the exact values', async ({ page }) => {
    await page.goto('/?particles=off&overview=1');
    await expect(dialog(page).locator('[data-el=ocean-transport] > title')).toHaveText(
      'Heat carried poleward by the ocean\nHeat carried poleward by the ocean: 2.100 PW',
    );
  });

  test('on a phone the overview does not open by itself and the button is hidden', async ({ browser }) => {
    const context = await browser.newContext({
      storageState: { cookies: [], origins: [] }, viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true,
    });
    const page = await context.newPage();
    await page.goto('/?particles=off');
    await ready(page);
    await expect(dialog(page)).toBeHidden();
    await expect(page.locator('.overview-open')).toBeHidden();
    await context.close();
  });
});
