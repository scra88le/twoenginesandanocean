import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import type { Manifest } from '../src/manifest';
import { DEFAULT_CENTER, parseCenter, readState, stateQuery, wrapLng, type ViewState } from '../src/urlstate';

const manifest = JSON.parse(
  readFileSync(new URL('../e2e/fixtures/data/manifest.json', import.meta.url), 'utf8'),
) as Manifest; // dates 2026-09-29..10-01; 12 layers built, incl. t_emit and net_toa

const read = (q: string) => readState(new URLSearchParams(q), manifest);

const FULL: ViewState = {
  layer: 'carnot', date: '2026-09-30', mode: 'anom', frame: '07', particles: { on: true, level: 'wind100' },
  arrows: true, center: [-30.25, 41.5], zoom: 3.25, pin: [10.25, 20.75],
};

test('a state survives the round trip through the query string', () => {
  const q = stateQuery('', FULL);
  expect(q).toBe('layer=carnot&mode=anom&frame=07&date=2026-09-30&center=-30.25,41.50&zoom=3.25&particles=wind100&arrows=1&pin=10.25,20.75');
  expect(read(q)).toEqual(FULL);
});

test('off switches are left out, and particles off is written explicitly', () => {
  const q = stateQuery('', { ...FULL, mode: 'today', arrows: false, pin: null, particles: { on: false, level: 'wind10' } });
  expect(q).toBe('layer=carnot&mode=today&frame=07&date=2026-09-30&center=-30.25,41.50&zoom=3.25&particles=off');
  const s = read(q);
  expect(s.mode).toBe('today');
  expect(s.arrows).toBe(false);
  expect(s.pin).toBeNull();
  expect(s.particles.on).toBe(false);
});

test('an empty URL gives the defaults: newest date, net radiation, 10 m particles, whole world', () => {
  expect(read('')).toEqual({
    layer: 'net_toa', date: '2026-10-01', mode: 'climate', frame: 'year', particles: { on: true, level: 'wind10' },
    arrows: false, center: DEFAULT_CENTER, zoom: 1.4, pin: null,
  });
});

test('invalid or stale values fall back to defaults one by one', () => {
  const s = read('layer=olr&date=2025-01-01&center=abc&zoom=99&particles=wind50&pin=10,95&anom=yes&arrows=2');
  expect(s.layer).toBe('net_toa'); // olr isn't built in the fixtures
  expect(s.date).toBe('2026-10-01'); // not a published date
  expect(s.center).toEqual(DEFAULT_CENTER);
  expect(s.zoom).toBe(1.4);
  expect(s.particles).toEqual({ on: true, level: 'wind10' });
  expect(s.pin).toBeNull();
  expect(s.mode).toBe('climate'); // net_toa's default
  expect(s.frame).toBe('year');
  expect(s.arrows).toBe(false);
  expect(read('layer=no_such_layer').layer).toBe('net_toa');
  expect(read('center=10,').center).toEqual(DEFAULT_CENTER); // a blank latitude is not 0
  expect(read('center=10,86').center).toEqual(DEFAULT_CENTER); // beyond the map
  expect(read('zoom=').zoom).toBe(1.4);
});

test('a valid date and layer are kept', () => {
  const s = read('layer=t_emit&date=2026-09-29');
  expect(s.layer).toBe('t_emit');
  expect(s.date).toBe('2026-09-29');
});

test('longitudes wrap into -180..180, so a map panned past the date line gives a sane link', () => {
  expect(wrapLng(190)).toBe(-170);
  expect(wrapLng(-190)).toBe(170);
  expect(wrapLng(540.5)).toBeCloseTo(-179.5, 9);
  expect(wrapLng(0.25)).toBe(0.25);
  expect(read('center=370.25,10').center).toEqual([10.25, 10]);
  expect(stateQuery('', { ...FULL, center: [200.5, 0], pin: null })).toContain('center=-159.50,0.00');
});

test('parameters the app does not own are kept, and ?tour is dropped once used', () => {
  const q = stateQuery('debug&tour=3&layer=olr&foo=bar', { ...FULL, mode: 'today', arrows: false, pin: null });
  expect(q).toBe('layer=carnot&mode=today&frame=07&date=2026-09-30&center=-30.25,41.50&zoom=3.25&particles=wind100&debug=&foo=bar');
});

test('the center parser needs two real numbers', () => {
  expect(parseCenter('1.5,-2')).toEqual([1.5, -2]);
  expect(parseCenter(null)).toBeNull();
  expect(parseCenter('1')).toBeNull();
  expect(parseCenter('1,2,3')).toBeNull();
  expect(parseCenter('a,b')).toBeNull();
  expect(parseCenter(',')).toBeNull();
});

test('the legacy ?anom=1 means mode=anom, and mode and frame validate one by one', () => {
  expect(read('layer=t_emit&anom=1').mode).toBe('anom');
  expect(read('layer=t_emit&mode=today&anom=1').mode).toBe('today'); // mode wins
  expect(read('layer=t_emit&mode=bogus&frame=13')).toMatchObject({ mode: 'today', frame: 'year' });
  expect(read('layer=net_toa&mode=today&frame=03')).toMatchObject({ mode: 'today', frame: '03' });
});

test('a layer that cannot show the asked mode opens in its own default', () => {
  expect(read('layer=j_ratio&mode=today').mode).toBe('climate');
  expect(read('layer=wind10&mode=climate').mode).toBe('today');
  expect(read('layer=net_toa').mode).toBe('climate');
  expect(read('layer=t_emit').mode).toBe('today');
});
