import { createReadStream, existsSync, statSync } from 'node:fs';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

const OUT_DIR = resolve(fileURLToPath(new URL('.', import.meta.url)), '../out');

const TYPES: Record<string, string> = {
  '.json': 'application/json',
  '.png': 'image/png',
  '.csv': 'text/csv',
  '.bin': 'application/octet-stream',
};

// Serves ../out under /data/ so the dev server uses the pipeline output as its data root.
function serveOut(): Plugin {
  return {
    name: 'serve-out',
    configureServer(server) {
      server.middlewares.use('/data', (req, res, next) => {
        const rel = normalize(decodeURIComponent((req.url ?? '/').split('?')[0] ?? '/'));
        const file = join(OUT_DIR, rel);
        if (!file.startsWith(OUT_DIR) || !existsSync(file) || !statSync(file).isFile()) {
          next();
          return;
        }
        res.setHeader('Content-Type', TYPES[extname(file)] ?? 'application/octet-stream');
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [serveOut()],
  test: {
    include: ['tests/**/*.test.ts'],
  },
});
