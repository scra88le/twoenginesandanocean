import { expect, test } from 'vitest';
import { colourAt, cssGradient, lutBytes, MAP_NAMES } from '../src/colormaps';

test('every catalogue colour scale is present with 256 entries', () => {
  expect([...MAP_NAMES].sort()).toEqual(
    ['BrBG', 'amp', 'balance', 'cividis', 'deep', 'inferno', 'magma', 'rain', 'thermal', 'viridis'],
  );
  for (const name of MAP_NAMES) expect(lutBytes(name).length).toBe(256 * 4);
});

test('viridis ends are the known colours', () => {
  expect(colourAt('viridis', 0)).toEqual([68, 1, 84]);
  expect(colourAt('viridis', 1)).toEqual([253, 231, 37]);
});

test('css gradient lists stops from 0% to 100%', () => {
  const g = cssGradient('viridis', 5);
  expect(g.startsWith('linear-gradient(to right, rgb(68, 1, 84) 0%')).toBe(true);
  expect(g.endsWith('rgb(253, 231, 37) 100%)')).toBe(true);
});

test('unknown scale throws', () => {
  expect(() => lutBytes('jet')).toThrow(/jet/);
});
