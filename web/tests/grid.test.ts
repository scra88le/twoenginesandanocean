import { expect, test } from 'vitest';
import { cellIndex } from '../src/grid';

const grid = { nlon: 720, nlat: 360, lon0: -179.75, lat0: 89.75, step: 0.5 };

test('cell centres map to their own cell', () => {
  expect(cellIndex(-179.75, 89.75, grid)).toEqual({ i: 0, j: 0 });
  expect(cellIndex(0.25, 19.75, grid)).toEqual({ i: 360, j: 140 });
  expect(cellIndex(179.75, -89.75, grid)).toEqual({ i: 719, j: 359 });
});

test('longitude wraps across world copies', () => {
  expect(cellIndex(360.25, 0.1, grid)).toEqual(cellIndex(0.25, 0.1, grid));
  expect(cellIndex(-180.25, 0.1, grid)).toEqual({ i: 719, j: 179 });
  expect(cellIndex(180, 0.1, grid)?.i).toBe(0);
});

test('latitude outside the grid gives null', () => {
  expect(cellIndex(0, 90.5, grid)).toBeNull();
  expect(cellIndex(0, -91, grid)).toBeNull();
});
