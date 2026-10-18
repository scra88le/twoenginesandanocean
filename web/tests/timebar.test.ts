import { expect, test } from 'vitest';
import { nearbyDates, stepIndex } from '../src/timebar';

const dates = ['2026-09-27', '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01'];

test('stepping stays inside the range', () => {
  expect(stepIndex(2, 1, 5)).toBe(3);
  expect(stepIndex(4, 1, 5)).toBe(4);
  expect(stepIndex(0, -1, 5)).toBe(0);
});

test('pre-fetch covers 3 days either side, nearest first', () => {
  expect(nearbyDates(dates, 2, 3)).toEqual(['2026-09-30', '2026-09-28', '2026-10-01', '2026-09-27']);
  expect(nearbyDates(dates, 4, 3)).toEqual(['2026-09-30', '2026-09-29', '2026-09-28']);
});
