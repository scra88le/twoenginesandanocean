import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

// Tests the production build (vite preview) on its own port, so a dev server is never reused.
const PORT = 5174;
const SUB_PORT = 5175; // the same build under a sub-path, as GitHub project pages serve it
const DATA_ROOT = fileURLToPath(new URL('./e2e/fixtures/data', import.meta.url));

export default defineConfig({
  testDir: 'e2e',
  // Every browser draws on the CPU (SwiftShader), so many at once slow each other down until
  // timing-sensitive tests fail. A handful of workers is faster in total than eleven.
  workers: process.env.CI ? 2 : 4,
  webServer: [
    {
      command: `npm run build && npx vite preview --port ${PORT} --strictPort`,
      url: `http://localhost:${PORT}`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { DATA_ROOT },
    },
    {
      // A separate output folder, so the two builds can't trip over each other.
      command: `npx vite build --outDir dist-sub && npx vite preview --outDir dist-sub --base /earth/ --port ${SUB_PORT} --strictPort`,
      url: `http://localhost:${SUB_PORT}/earth/`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { DATA_ROOT },
    },
  ],
  use: {
    baseURL: `http://localhost:${PORT}`,
    viewport: { width: 1000, height: 700 },
    deviceScaleFactor: 1,
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
});
