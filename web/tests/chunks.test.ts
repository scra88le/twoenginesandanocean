import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { parseSeries, pointCodes, seriesCodes, tileOf } from '../src/chunks';
import { cellIndex } from '../src/grid';
import type { Manifest } from '../src/manifest';
import { formatPlace, readoutItems, seriesData } from '../src/readout';

// Fixtures from pipeline/scripts/make_web_fixtures.py, written by the real pipeline.
const root = new URL('../e2e/fixtures/data/', import.meta.url);
const read = (path: string) => {
  const b = readFileSync(new URL(path, root));
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
};
const manifest = JSON.parse(readFileSync(new URL('manifest.json', root), 'utf8')) as Manifest;
const points = manifest.points!;

const SOUTH = cellIndex(0.25, -35.25, manifest.grid)!; // open sea
const NORTH = cellIndex(0.25, 35.25, manifest.grid)!; // "land" in the fixtures

test('cells map to their tile and the index within it', () => {
  expect(SOUTH).toEqual({ i: 360, j: 250 });
  expect(tileOf(SOUTH, 20)).toEqual({ tx: 18, ty: 12, k: 200 });
  expect(tileOf({ i: 719, j: 359 }, 20)).toEqual({ tx: 35, ty: 17, k: 399 });
});

test('the manifest describes the point chunks: 24 layers then the extras', () => {
  expect(points.tile).toBe(20);
  expect(points.fields.length).toBe(26);
  expect(points.fields.slice(-2)).toEqual(['t_skin', 'j_opt']);
  expect(manifest.series!.file).toBe('series/{layer}/{tx}_{ty}.bin');
});

test('a point chunk gives every field at a cell, decoded to readout text', () => {
  const { k } = tileOf(SOUTH, 20);
  const codes = pointCodes(read('points/2026-10-01/18_12.bin'), points.fields, 20, k);
  const rows = readoutItems(manifest, codes);
  const item = (id: string) => rows.flatMap((r) => r.items).find((x) => x.id === id)!;
  expect(rows.map((r) => r.label)).toEqual([
    'Fuel', 'Hot side', 'Cold side', 'Ceiling', 'Max power', 'Actual', 'Split', 'Output', 'Water', 'Humans',
  ]);
  expect(item('t_emit').text).toBe('236.00 K (−37.1 °C)');
  expect(item('t_skin').text).toBe('300.00 K (26.9 °C)');
  expect(item('carnot').text).toBe('0.00 %');
  expect(item('j_opt')).toMatchObject({ text: '—' });
  expect(item('j_opt').note).toMatch(/^Ocean and sea ice/);
  expect(item('asr_sfc').text).toBe('not available yet'); // not built in the fixtures
  expect(item('human_q').text).toBe('not available yet');
});

test('on land the extras have values', () => {
  const codes = pointCodes(read('points/2026-10-01/18_5.bin'), points.fields, 20, tileOf(NORTH, 20).k);
  const item = (id: string) => readoutItems(manifest, codes).flatMap((r) => r.items).find((x) => x.id === id)!;
  expect(item('j_opt').text).toBe('100.00 W m⁻²');
  expect(item('carnot').text).toBe('15.00 %');
});

test('point chunks of the wrong size are rejected', () => {
  expect(() => pointCodes(new ArrayBuffer(10), points.fields, 20, 0)).toThrow(/bytes/);
});

test('a series chunk lists its dates and gives one value per date at a cell', () => {
  const s = parseSeries(read('series/t_emit/18_12.bin'), 20);
  expect(s.dates).toEqual(['2026-09-29', '2026-09-30', '2026-10-01']);
  const [xs, ys] = seriesData(s.dates, seriesCodes(s, 20, tileOf(SOUTH, 20).k), manifest.layers.t_emit!.encode);
  expect(ys.map((y) => y!.toFixed(2))).toEqual(['226.00', '231.00', '236.00']);
  expect(xs[1]! - xs[0]!).toBe(86400);
});

test('dates without a value become gaps in the chart', () => {
  const s = parseSeries(read('series/wind10/18_12.bin'), 20);
  const [, ys] = seriesData(s.dates, seriesCodes(s, 20, 0), manifest.layers.wind10!.encode);
  expect(ys[0]).toBeNull(); // no wind10 on 2026-09-29
  expect(ys[2]).toBeCloseTo(10, 6);
});

test('a non-series file is rejected', () => {
  expect(() => parseSeries(read('points/2026-10-01/18_12.bin'), 20)).toThrow(/series/);
});

test('places read as degrees north/south and east/west', () => {
  expect(formatPlace(0.25, -35.25)).toBe('35.25° S, 0.25° E');
  expect(formatPlace(-120.75, 40.25)).toBe('40.25° N, 120.75° W');
});

test('missing dates become gaps, so the chart never joins across them', () => {
  const enc = manifest.layers.t_emit!.encode;
  const code = (v: number) => Math.round((v - enc.offset) / enc.scale) + 2;
  const [xs, ys] = seriesData(['2026-08-30', '2026-08-31', '2026-09-03'], Uint16Array.of(code(250), 1, code(260)), enc);
  expect(xs.length).toBe(5); // Aug 30 to Sep 3, one per day
  expect(ys.map((y) => (y === null ? null : Math.round(y)))).toEqual([250, null, null, null, 260]);
  expect(seriesData([], new Uint16Array(0), enc)).toEqual([[], []]);
});
