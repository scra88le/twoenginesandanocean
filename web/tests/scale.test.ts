import { describe, expect, test } from 'vitest';
import { autoRange, displayScale, ticks, toT } from '../src/scale';
import type { LayerMeta } from '../src/manifest';

const meta = (over: Partial<LayerMeta>): LayerMeta => ({
  title: 't', group: 1, group_name: 'Fuel', units: 'W m-2', colour: 'viridis', display: [0, 100],
  log: false, centre: null, vector: false, anomaly: true,
  encode: { lo: 0, hi: 200, log: false, scale: 0.1, offset: 0 }, uv_encode: null, anomaly_encode: null,
  hatch_zero: false,
  info: { summary: '', source: '', formula: '', sign: '', meaning: '', caveats: '', mask: null },
  ...over,
});

describe('toT', () => {
  test('linear maps the display range to 0..1 and clamps', () => {
    const s = displayScale(meta({}));
    expect(toT(0, s)).toBe(0);
    expect(toT(25, s)).toBe(0.25);
    expect(toT(100, s)).toBe(1);
    expect(toT(-5, s)).toBe(0);
    expect(toT(500, s)).toBe(1);
  });

  test('log maps decades evenly', () => {
    const s = displayScale(meta({ display: [0.1, 100], log: true }));
    expect(toT(0.1, s)).toBeCloseTo(0, 12);
    expect(toT(1, s)).toBeCloseTo(1 / 3, 12);
    expect(toT(100, s)).toBeCloseTo(1, 12);
  });

  test('a centre maps to 0.5 even when the range is not symmetric around it', () => {
    const s = displayScale(meta({ display: [1e-4, 10], log: true, centre: 1 }));
    expect(toT(1, s)).toBeCloseTo(0.5, 12);
    expect(toT(1e-4, s)).toBeCloseTo(0, 12);
    expect(toT(10, s)).toBeCloseTo(1, 12);
    expect(toT(1e-2, s)).toBeCloseTo(0.25, 12); // halfway in log between 1e-4 and 1
  });
});

describe('auto range', () => {
  const values = Float64Array.from({ length: 1001 }, (_, k) => k - 500); // -500..500

  test('2nd to 98th percentile, ignoring NaN', () => {
    const withNaN = Float64Array.from([...values, NaN, NaN]);
    const [lo, hi] = autoRange(withNaN, false);
    expect(lo).toBeCloseTo(-480, 6);
    expect(hi).toBeCloseTo(480, 6);
  });

  test('symmetric about zero for diverging scales', () => {
    const skewed = Float64Array.from({ length: 1001 }, (_, k) => k - 200); // -200..800
    const [lo, hi] = autoRange(skewed, true);
    expect(lo).toBe(-hi);
    expect(hi).toBeCloseTo(780, 6);
  });

  test('displayScale uses the data for "auto" layers', () => {
    const s = displayScale(meta({ display: 'auto', centre: 0 }), values);
    expect(s.lo).toBeCloseTo(-480, 6);
    expect(s.hi).toBeCloseTo(480, 6);
  });
});

describe('ticks', () => {
  test('log scales are labelled with powers of ten', () => {
    const t = ticks(displayScale(meta({ display: [0.01, 20], log: true })));
    expect(t.map((x) => x.value)).toEqual([0.01, 0.1, 1, 10]);
    expect(t.map((x) => x.label)).toEqual(['10⁻²', '10⁻¹', '10⁰', '10¹']);
  });

  test('linear ticks are round numbers inside the range', () => {
    const t = ticks(displayScale(meta({ display: [-200, 200] })));
    expect(t.map((x) => x.value)).toEqual([-200, -100, 0, 100, 200]);
    for (const x of t) expect(x.t).toBeGreaterThanOrEqual(0);
  });
});
