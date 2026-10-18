import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

// Tests the production build (vite preview) on its own port, so a dev server is never reused.
const PORT = 5174;

export default defineConfig({
  testDir: 'e2e',
  webServer: {
    command: `npm run build && npx vite preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    timeout: 120_000,
    reuseExistingServer: false,
    env: { DATA_ROOT: fileURLToPath(new URL('./e2e/fixtures/data', import.meta.url)) },
  },
  use: {
    baseURL: `http://localhost:${PORT}`,
    viewport: { width: 1000, height: 700 },
    deviceScaleFactor: 1,
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
});
