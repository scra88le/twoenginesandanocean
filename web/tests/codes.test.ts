import { expect, test } from 'vitest';
import { FIRST_VALID, MASKED, NODATA, decodeValue } from '../src/codes';

const linear = { lo: -400, hi: 400, log: false, scale: 0.25, offset: -400 };
const log = { lo: 1e-3, hi: 1e3, log: true, scale: 0.002, offset: -3 };

test('reserved codes', () => {
  expect([NODATA, MASKED, FIRST_VALID]).toEqual([0, 1, 2]);
  expect(decodeValue(0, linear)).toBeNaN();
  expect(decodeValue(1, linear)).toBeNaN();
});

test('linear decode matches the manifest formula', () => {
  expect(decodeValue(2, linear)).toBe(-400);
  expect(decodeValue(1602, linear)).toBe(0);
  expect(decodeValue(3202, linear)).toBe(400);
});

test('log decode is in log10 space', () => {
  expect(decodeValue(2, log)).toBeCloseTo(1e-3, 12);
  expect(decodeValue(1502, log)).toBeCloseTo(1, 10);
  expect(decodeValue(3002, log)).toBeCloseTo(1e3, 6);
});
