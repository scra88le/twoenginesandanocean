import { expect, test } from 'vitest';
import {
  amocTrend, amocTrendText, compassTo, describeLimb, hexToRgb, limbDepth, oceanAvailable, oceanCaption, oceanUrl, parseSection, psiColour,
  resolveAvg, sectionAvg, sectionStrength, sectionText, sectionUrl, type LimbMeta, type OceanMeta, type SectionGrid,
} from '../src/ocean';

const enc = { lo: 0, hi: 1, log: false, scale: 1, offset: 0 };
const limb = (bottom: number | null): LimbMeta => ({
  title: 't', colour: '#f08a5d', top_m: bottom === null ? 1100 : 0, bottom_m: bottom, units: 'm2 s-1', uv_units: 'm s-1',
  display: [1, 1000], encode: enc, uv_encode: enc, speed_hi: 0.3, density_ref: 200,
});
const section = { psi_max_sv: 16.84, z_max_m: 1153.5, amoc_upper_sv: 16.2, amoc_deep_sv: -15.47 };
const O: OceanMeta = {
  product: 'GLOBAL_ANALYSISFORECAST_PHY_001_024',
  dataset: 'cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m',
  split_m: 1100,
  window_days: 30,
  section: { lat: 26.5, lon: [-81, -13] },
  files: { field: 'ocean/{date}/{limb}{avg}.png', uv: 'ocean/{date}/{limb}{avg}_uv.png', section: 'ocean/{date}/section{avg}.json', avg: { daily: '', mean: '_30d' } },
  section_grid: { lat0: -1, dlat: 0.5, n_lat: 5, depth_edges_m: [0, 10, 300, 1100], unit_sv: 0.1 },
  limbs: { amoc_upper: limb(1100), amoc_deep: limb(null) },
  dates: {
    '2026-10-17': { window_days: 12, daily: section, mean: null, section: { daily: true, mean: false } },
    '2026-10-18': { window_days: 30, daily: section, mean: { ...section, psi_max_sv: 17.04 }, section: { daily: true, mean: true } },
  },
  info: { summary: '', source: '', formula: '', sign: '', meaning: '', caveats: '', mask: null, anomaly: '' },
  credit: '',
};

test('file names follow the manifest templates', () => {
  expect(oceanUrl('/data', O, '2026-10-18', 'amoc_deep', 'mean', true)).toBe('/data/ocean/2026-10-18/amoc_deep_30d_uv.png');
  expect(oceanUrl('/data', O, '2026-10-18', 'amoc_upper', 'daily', false)).toBe('/data/ocean/2026-10-18/amoc_upper.png');
});

test('a date offers the mean only once its window has filled, and falls back to what it has', () => {
  expect(oceanAvailable(O, '2026-10-17')).toEqual({ daily: true, mean: false });
  expect(oceanAvailable(O, '2026-10-01')).toEqual({ daily: false, mean: false });
  expect(oceanAvailable(null, '2026-10-18')).toEqual({ daily: false, mean: false });
  expect(resolveAvg(O, '2026-10-18', 'mean')).toBe('mean');
  expect(resolveAvg(O, '2026-10-17', 'mean')).toBe('daily');
  expect(resolveAvg(O, '2026-10-01', 'daily')).toBeNull();
});

test('the caption names the period and the 26.5 N figures of the limbs drawn', () => {
  const c = oceanCaption(O, '2026-10-18', { on: true, limbs: 'both', avg: 'mean' }, 'mean');
  expect(c).toBe(
    'Ocean overturning (GLO12, 30-day mean to 2026-10-18): across 26.5° N, upper limb 16.2 Sv north, ' +
      'deep limb 15.5 Sv south; AMOC 17.0 Sv at 1,154 m',
  );
  const d = oceanCaption(O, '2026-10-17', { on: true, limbs: 'deep', avg: 'daily' }, 'daily');
  expect(d).toContain('daily mean, 2026-10-17');
  expect(d).not.toContain('upper limb');
});

test('currents are named by where they flow to', () => {
  expect(compassTo(0, 1)).toBe('N');
  expect(compassTo(1, 1)).toBe('NE');
  expect(compassTo(0, -1)).toBe('S');
  expect(compassTo(-1, 0)).toBe('W');
  expect(describeLimb('Upper limb', 312.4, 0.2, 0.2)).toBe('Upper limb: 312 m²/s, 0.28 m/s toward NE');
  expect(describeLimb('Deep limb', 42.25, 0, -0.012)).toBe('Deep limb: 42.3 m²/s, 0.012 m/s toward S');
  expect(describeLimb('Deep limb', NaN, NaN, NaN)).toBe('Deep limb: none here');
});

test('limb depths and colours', () => {
  expect(limbDepth(limb(1100))).toBe('0–1,100 m');
  expect(limbDepth(limb(null))).toBe('below 1,100 m');
  expect(hexToRgb('#ff8000').map((x) => +x.toFixed(3))).toEqual([1, 0.502, 0]);
  expect(hexToRgb('nope')).toEqual([1, 1, 1]);
});

test('the trend lists every date oldest first, with the mean null until its window is in', () => {
  const tr = amocTrend(O);
  expect(tr.dates).toEqual(['2026-10-17', '2026-10-18']);
  expect(tr.daily).toEqual([16.84, 16.84]);
  expect(tr.mean).toEqual([null, 17.04]);
  expect(tr.t[1]! - tr.t[0]!).toBe(86_400);
});

test('the trend text states the latest strength and the change of the mean', () => {
  expect(amocTrendText(amocTrend(O))).toEqual([
    '2 days of ocean currents, 2026-10-17 to 2026-10-18.',
    'Daily AMOC strength on 2026-10-18: 16.8 Sv.',
    '30-day mean to 2026-10-18: 17.0 Sv.',
  ]);
  expect(amocTrendText({ dates: [], t: [], daily: [], mean: [] })).toEqual([]);
});

const GRID = O.section_grid as SectionGrid;
// Three levels (bottom edges 10, 300 and 1100 m) by five latitudes (-1 to 1); the last latitude has no water.
const RAW = { psi: [[1, 2, 3, 2, null], [50, 100, 160, 120, null], [20, 90, 170, 100, null]] };

test('section files follow the manifest template and fall back from the mean to the daily', () => {
  expect(sectionUrl('/data', O, '2026-10-18', 'mean')).toBe('/data/ocean/2026-10-18/section_30d.json');
  expect(sectionUrl('/data', O, '2026-10-18', 'daily')).toBe('/data/ocean/2026-10-18/section.json');
  expect(sectionAvg(O, '2026-10-18', 'mean')).toBe('mean');
  expect(sectionAvg(O, '2026-10-17', 'mean')).toBe('daily');
  expect(sectionAvg(O, '2026-10-01', 'mean')).toBeNull();
  expect(sectionAvg({ ...O, section_grid: null }, '2026-10-18', 'mean')).toBeNull();
});

test('a section is unpacked from tenths of a Sv, null as no water, and checked against the grid', () => {
  const sec = parseSection(RAW, GRID);
  expect(sec.lat).toEqual([-1, -0.5, 0, 0.5, 1]);
  expect(sec.psi[1]![2]).toBeCloseTo(16);
  expect(sec.psi[0]![4]).toBeNaN();
  expect(() => parseSection({ psi: RAW.psi.slice(1) }, GRID)).toThrow(/levels/);
  expect(() => parseSection({ psi: RAW.psi.map((r) => r.slice(1)) }, GRID)).toThrow(/latitudes/);
  expect(() => parseSection(null, GRID)).toThrow();
});

test('the strength at each latitude is the largest psi down the column, with its depth', () => {
  const { sv, z } = sectionStrength(parseSection(RAW, GRID));
  expect(sv.slice(0, 4)).toEqual([5, 10, 17, 12].map((x) => expect.closeTo(x, 5)));
  expect(z.slice(0, 4)).toEqual([300, 300, 1100, 300]);
  expect(sv[4]).toBeNaN();
});

test('colours: dark at zero, warm for positive, cold for negative, full at the limit', () => {
  expect(psiColour(0, 25)).toEqual([27, 31, 39]);
  expect(psiColour(25, 25)).toEqual([240, 138, 93]);
  expect(psiColour(99, 25)).toEqual([240, 138, 93]);
  expect(psiColour(-25, 25)).toEqual([111, 182, 242]);
  expect(psiColour(NaN, 25)).toEqual([0, 0, 0]);
});

test('the section text names the strongest latitude and depth, and the figures at set latitudes', () => {
  const lines = sectionText(parseSection(RAW, GRID), O);
  expect(lines[0]).toBe('Strongest overturning: 17.0 Sv at 0.0° N, 1,100 m deep.');
  expect(lines).toContain('The equator: 17.0 Sv at 1,100 m.');
});
