import { expect, test } from 'vitest';
import { formatValue, prettyUnits } from '../src/format';

const enc = (scale: number, log = false) => ({ lo: 0, hi: 1, log, scale, offset: 0 });

test('units get superscript exponents', () => {
  expect(prettyUnits('W m-2')).toBe('W m⁻²');
  expect(prettyUnits('mm day-1')).toBe('mm day⁻¹');
  expect(prettyUnits('m s-1')).toBe('m s⁻¹');
  expect(prettyUnits('K')).toBe('K');
});

test('decimals follow the layer resolution', () => {
  expect(formatValue(243.75, 'W m-2', enc(0.25))).toBe('243.75 W m⁻²');
  expect(formatValue(243.6, 'W m-2', enc(0.2))).toBe('243.6 W m⁻²');
  expect(formatValue(-38, 'W m-2', enc(1))).toBe('−38 W m⁻²');
});

test('kelvin also shows degrees Celsius in brackets', () => {
  expect(formatValue(255.06, 'K', enc(0.02))).toBe('255.06 K (−18.1 °C)');
});

test('log layers use three significant figures', () => {
  expect(formatValue(0.012345, 'W m-2', enc(0.002, true))).toBe('0.0123 W m⁻²');
  expect(formatValue(1234.5, 'mm day-1', enc(0.002, true))).toBe('1230 mm day⁻¹');
});

test('very large values use exponent notation', () => {
  expect(formatValue(2.41e8, 'W m-1', enc(1e6))).toBe('2.41 × 10⁸ W m⁻¹');
});

test('missing values', () => {
  expect(formatValue(NaN, 'K', enc(0.02))).toBe('no data');
});

test('log layers read "less than" at the encode floor, where zero is stored', async () => {
  const { formatReading } = await import('../src/format');
  const precip = { lo: 1e-3, hi: 1e3, log: true, scale: 0.002, offset: -3 };
  expect(formatReading(1e-3, 'mm day-1', precip)).toBe('< 0.001 mm day⁻¹');
  expect(formatReading(0.05, 'mm day-1', precip)).toBe('0.05 mm day⁻¹');
  expect(formatReading(255.06, 'K', enc(0.02))).toBe('255.06 K (−18.1 °C)');
});
