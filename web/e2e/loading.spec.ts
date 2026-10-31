import { expect, test } from '@playwright/test';

// A visible "Loading map…" from first paint until the first raster draws (F11 §2).
test('a loading indicator shows until the first raster is on screen, then goes', async ({ page }) => {
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  // hold the first raster back, as a slow connection would
  await page.route('**/fields/**/t_emit.png', async (route) => {
    await gate;
    await route.continue();
  });
  await page.goto('/?layer=t_emit&particles=off');
  const loading = page.locator('#loading');
  await expect(loading).toBeVisible();
  await expect(loading).toHaveText('Loading map…');
  await expect(loading).toHaveAttribute('role', 'status');
  await expect(page.locator('body')).not.toHaveAttribute('data-drawn', 'true');
  release();
  await expect(page.locator('body')).toHaveAttribute('data-drawn', 'true', { timeout: 20_000 });
  await expect(loading).toHaveCount(0);
});

test('a layer with no data for the first date still clears the indicator', async ({ page }) => {
  await page.route('**/fields/**/t_emit.png', (route) => route.fulfill({ status: 404, body: 'Not found' }));
  await page.goto('/?layer=t_emit&particles=off');
  await expect(page.locator('body')).toHaveAttribute('data-drawn', 'true', { timeout: 20_000 });
  await expect(page.locator('#loading')).toHaveCount(0);
  await expect(page.locator('#legend')).toContainText('No data for');
});
