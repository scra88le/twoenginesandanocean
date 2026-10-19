import { expect, test } from 'vitest';
import { arrowInstances, arrowReference, arrowSpacing, sampleUV, type ArrowField } from '../src/layers/arrows';

const grid = { nlon: 720, nlat: 360, lon0: -179.75, lat0: 89.75, step: 0.5 };
const enc = { lo: -1.5e9, hi: 1.5e9, log: false, scale: 1e6, offset: -1.5e9 };
const code = (x: number) => Math.round((x - enc.offset) / enc.scale) + 2;
const N = 720 * 360;

function field(u: number, v: number, reference = Math.hypot(u, v), blank?: (i: number, j: number) => boolean): ArrowField {
  const cu = new Uint16Array(N).fill(code(u));
  const cv = new Uint16Array(N).fill(code(v));
  if (blank) {
    for (let j = 0; j < 360; j++) for (let i = 0; i < 720; i++) if (blank(i, j)) cu[j * 720 + i] = cv[j * 720 + i] = 0;
  }
  return { u: cu, v: cv, encode: enc, grid, reference };
}

// The whole world fills a square view: clip x = 2 mx - 1, clip y = 1 - 2 my. (Column-major.)
const INV = [0.5, 0, 0, 0, 0, -0.5, 0, 0, 0, 0, 1, 0, 0.5, 0.5, 0, 1];
// The same view shifted so that it straddles the antimeridian: mx runs from 0.75 to 1.25.
const INV_WRAP = [0.25, 0, 0, 0, 0, -0.5, 0, 0, 0, 0, 1, 0, 1, 0.5, 0, 1];

const chunks = (a: Float32Array) => Array.from({ length: a.length / 4 }, (_, k) => Array.from(a.subarray(4 * k, 4 * k + 4)));

test('the grid spacing is wider on phones', () => {
  expect(arrowSpacing(1280)).toBe(44);
  expect(arrowSpacing(390)).toBe(52);
});

test('arrows follow the flux direction on screen: east is right, north is up', () => {
  const east = chunks(arrowInstances(INV, 440, 440, 44, field(5e8, 0)));
  expect(east.length).toBeGreaterThan(50);
  for (const [, , dx, dy] of east) {
    expect(dx).toBeGreaterThan(0);
    expect(Math.abs(dy!)).toBeLessThan(1e-3);
  }
  const north = chunks(arrowInstances(INV, 440, 440, 44, field(0, 5e8)));
  for (const [, , dx, dy] of north) {
    expect(dy).toBeGreaterThan(0); // clip y is up
    expect(Math.abs(dx!)).toBeLessThan(1e-3);
  }
  const [, , dx, dy] = chunks(arrowInstances(INV, 440, 440, 44, field(-3e8, -4e8)))[0]!;
  expect(dx).toBeLessThan(0);
  expect(dy).toBeLessThan(0);
  expect(dy! / dx!).toBeCloseTo(4 / 3, 2);
});

test('length is proportional to the flux up to the reference, then capped at 90% of a cell', () => {
  const len = (u: number, ref: number) => {
    const [, , dx, dy] = chunks(arrowInstances(INV, 440, 440, 44, field(u, 0, ref)))[0]!;
    return Math.hypot(dx!, dy!);
  };
  expect(len(5e8, 5e8)).toBeCloseTo(39.6, 3);
  expect(len(5e8, 1e9)).toBeCloseTo(19.8, 3); // half the reference
  expect(len(9e8, 3e8)).toBeCloseTo(39.6, 3); // beyond it: capped
  expect(arrowInstances(INV, 440, 440, 44, field(1e7, 0, 1e9)).length).toBe(0); // too short to see
});

test('arrows sit on a centred screen grid and are given in clip coordinates', () => {
  const a = chunks(arrowInstances(INV, 440, 440, 44, field(5e8, 0)));
  const xs = [...new Set(a.map((r) => r[0]!.toFixed(6)))].map(Number).sort((p, q) => p - q);
  expect(xs.length).toBe(10);
  expect(xs[0]).toBeCloseTo((22 / 440) * 2 - 1, 6); // the first centre is half a cell in
  expect(xs[1]! - xs[0]!).toBeCloseTo((44 / 440) * 2, 6);
});

test('cells with no data get no arrow', () => {
  const west = chunks(arrowInstances(INV, 440, 440, 44, field(5e8, 0, 5e8, (i) => i >= 360)));
  expect(west.length).toBeGreaterThan(20);
  for (const [cx] of west) expect(cx).toBeLessThan(0.05); // only the western half of the world
});

test('a view that crosses the antimeridian still finds the flux on both sides', () => {
  const a = chunks(arrowInstances(INV_WRAP, 440, 440, 44, field(5e8, 0)));
  expect(a.some((r) => r[0]! < -0.5)).toBe(true);
  expect(a.some((r) => r[0]! > 0.5)).toBe(true);
  expect(a.length).toBeGreaterThan(50);
});

test('sampling interpolates between cells and skips invalid ones', () => {
  const f = field(0, 0);
  f.u[100 * 720 + 360] = code(4e8); // the cell centred on 0.25 E, 39.75 N
  expect(sampleUV(f, 0.25, 39.75)![0]).toBeCloseTo(4e8, -5);
  const mid = sampleUV(f, 0.5, 39.75)![0]; // the boundary with the next cell
  expect(mid).toBeGreaterThan(1.9e8);
  expect(mid).toBeLessThan(2.1e8);
  expect(sampleUV(field(5e8, 0, 1, () => true), 0, 0)).toBeNull();
});

test('the reference flux is the 98th percentile of the magnitude', () => {
  const f = field(1e8, 0);
  for (let k = 0; k < 2000; k++) f.u[k] = code(9e8); // under 1% of the cells are strong
  expect(arrowReference(f.u, f.v, enc)).toBeCloseTo(1e8, -6);
  for (let k = 0; k < 20_000; k++) f.u[k] = code(9e8); // about 8%: now the 98th percentile is strong
  expect(arrowReference(f.u, f.v, enc)).toBeCloseTo(9e8, -6);
  expect(arrowReference(new Uint16Array(4), new Uint16Array(4), enc)).toBe(1); // nothing valid
});
