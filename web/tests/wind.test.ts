import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import type { Manifest } from '../src/manifest';
import { builtLevels } from '../src/overlays';
import { PX_PER_S_AT_HI, compassFrom, describeWind, mercatorStep, particleCount, windAt } from '../src/wind';

const manifest = JSON.parse(
  readFileSync(new URL('../e2e/fixtures/data/manifest.json', import.meta.url), 'utf8'),
) as Manifest;

test('compass names the direction the wind blows from', () => {
  expect(compassFrom(10, 0)).toBe('W'); // blowing east
  expect(compassFrom(-10, 0)).toBe('E');
  expect(compassFrom(0, 10)).toBe('S'); // blowing north
  expect(compassFrom(0, -10)).toBe('N');
  expect(compassFrom(5, 5)).toBe('SW');
  expect(compassFrom(-5, -5)).toBe('NE');
  expect(compassFrom(-0.1, -10)).toBe('N'); // just west of north still rounds to N
});

test('wind is described as speed and direction, or calm', () => {
  expect(describeWind({ u: 3, v: 4 })).toBe('5.0 m/s from SW');
  expect(describeWind({ u: 0.01, v: 0 })).toBe('calm');
});

test('windAt decodes u and v in the cell under a point', () => {
  const enc = manifest.layers.wind10!.uv_encode!; // linear, step 0.1, from -60
  const n = 720 * 360;
  const code = (x: number) => Math.round((x - enc.offset) / enc.scale) + 2;
  const u = new Uint16Array(n).fill(code(0));
  const v = new Uint16Array(n).fill(code(0));
  const k = 100 * 720 + 360; // cell centred on 0.25 E, 39.75 N
  u[k] = code(-4.2);
  v[k] = code(7.5);
  const w = windAt(u, v, enc, manifest.grid, 0.3, 39.8)!;
  expect(w.u).toBeCloseTo(-4.2, 9);
  expect(w.v).toBeCloseTo(7.5, 9);
  u[k] = 0; // no data
  expect(windAt(u, v, enc, manifest.grid, 0.3, 39.8)).toBeNull();
  expect(windAt(u, v, enc, manifest.grid, 0, 90.5)).toBeNull(); // off the grid
});

test('particle count follows the canvas area and is halved on narrow screens', () => {
  expect(particleCount(1800, 800)).toBe(16000);
  expect(particleCount(900, 800)).toBe(8000);
  expect(particleCount(675, 800)).toBe(3000); // a quarter less area, then halved for phones
  expect(particleCount(100, 100)).toBe(1024); // floor
  expect(particleCount(4000, 3000)).toBe(32768); // cap
});

test('a wind at the top of the colour range moves at a fixed screen speed at any zoom', () => {
  for (const zoom of [0, 2.5, 6]) {
    const worldPx = 512 * 2 ** zoom;
    expect(mercatorStep(25, zoom, 1) * 25 * worldPx).toBeCloseTo(PX_PER_S_AT_HI, 9);
  }
  expect(mercatorStep(80, 3, 0.5)).toBeCloseTo(mercatorStep(80, 3, 1) / 2, 15);
});

test('only built wind levels with u, v files are offered', () => {
  expect(builtLevels(manifest)).toEqual(['wind10', 'wind100', 'jet250']);
});
