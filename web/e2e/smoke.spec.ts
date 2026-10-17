import { expect, test } from '@playwright/test';

test('page loads', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#app')).toHaveText('Earth Heat Engine Map');
});
