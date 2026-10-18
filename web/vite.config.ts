import { createReadStream, existsSync, statSync } from 'node:fs';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

const HERE = fileURLToPath(new URL('.', import.meta.url));
// DATA_ROOT overrides the data root (the e2e test points it at e2e/fixtures/data).
const OUT_DIR = resolve(HERE, process.env.DATA_ROOT ?? '../out');

const TYPES: Record<string, string> = {
  '.json': 'application/json',
  '.png': 'image/png',
  '.csv': 'text/csv',
  '.bin': 'application/octet-stream',
};

// Serves the data root under /data/ in `vite dev` and `vite preview`.
function serveOut(): Plugin {
  const handler = (
    req: { url?: string },
    res: import('node:http').ServerResponse,
    next: () => void,
  ) => {
    const rel = normalize(decodeURIComponent((req.url ?? '/').split('?')[0] ?? '/'));
    const file = join(OUT_DIR, rel);
    if (!file.startsWith(OUT_DIR + sep) || !existsSync(file) || !statSync(file).isFile()) {
      next();
      return;
    }
    res.setHeader('Content-Type', TYPES[extname(file)] ?? 'application/octet-stream');
    createReadStream(file).pipe(res);
  };
  return {
    name: 'serve-out',
    configureServer: (server) => void server.middlewares.use('/data', handler),
    configurePreviewServer: (server) => void server.middlewares.use('/data', handler),
  };
}

export default defineConfig({
  plugins: [serveOut()],
  test: {
    include: ['tests/**/*.test.ts'],
  },
});
