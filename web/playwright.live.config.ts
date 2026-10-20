import { defineConfig } from '@playwright/test';

// The smoke test against a deployed site: SITE_URL=https://... npm run smoke
// (see e2e-live/smoke.spec.ts). It starts no server; the site and its data are already live.
const site = process.env.SITE_URL;
if (!site) throw new Error('Set SITE_URL to the address of the deployed site, e.g. SITE_URL=https://example.org/earth/');

export default defineConfig({
  testDir: 'e2e-live',
  timeout: 90_000,
  retries: 1, // a cold CDN or a slow first request is not a failed deployment
  use: {
    baseURL: site.endsWith('/') ? site : `${site}/`,
    viewport: { width: 1000, height: 700 },
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
});
