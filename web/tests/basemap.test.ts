import { expect, test } from 'vitest';
import { assetUrl } from '../src/basemap';

test('assets resolve against the page, so the site works from any path', () => {
  expect(assetUrl('basemap/a.geojson', './', 'https://example.org/earth/')).toBe('https://example.org/earth/basemap/a.geojson');
  expect(assetUrl('basemap/a.geojson', './', 'https://example.org/earth/index.html')).toBe('https://example.org/earth/basemap/a.geojson');
  expect(assetUrl('basemap/a.geojson', './', 'http://localhost:5174/')).toBe('http://localhost:5174/basemap/a.geojson');
  expect(assetUrl('basemap/a.geojson', '/', 'https://x.io/anything/')).toBe('https://x.io/basemap/a.geojson');
});
