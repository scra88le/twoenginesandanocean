import { expect, test } from 'vitest';
import {
  compassTo, describeLimb, hexToRgb, limbDepth, oceanAvailable, oceanCaption, oceanUrl, resolveAvg, type LimbMeta, type OceanMeta,
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
  files: { field: 'ocean/{date}/{limb}{avg}.png', uv: 'ocean/{date}/{limb}{avg}_uv.png', avg: { daily: '', mean: '_30d' } },
  limbs: { amoc_upper: limb(1100), amoc_deep: limb(null) },
  dates: {
    '2026-10-17': { window_days: 12, daily: section, mean: null },
    '2026-10-18': { window_days: 30, daily: section, mean: { ...section, psi_max_sv: 17.04 } },
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
