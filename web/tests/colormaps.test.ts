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

// Relative luminance (sRGB, Rec. 709 weights): enough to say which end of a scale is brighter.
const luminance = ([r, g, b]: [number, number, number]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;

test('sequential scales get brighter from low to high, so low values are dark on the dark theme', () => {
  const diverging = ['BrBG', 'balance']; // centred on a pale or neutral middle, by design
  for (const name of MAP_NAMES.filter((n) => !diverging.includes(n))) {
    const [lo, mid, hi] = [0, 0.5, 1].map((t) => luminance(colourAt(name, t)));
    expect(lo, `${name}: low`).toBeLessThan(mid!);
    expect(mid, `${name}: mid`).toBeLessThan(hi!);
    expect(lo, `${name}: low is dark`).toBeLessThan(70);
  }
});

test('the water and heat scales that used to start near white are the reversed ones', () => {
  expect(colourAt('rain', 0)).toEqual([34, 27, 56]);
  expect(colourAt('rain', 1)).toEqual([238, 237, 243]);
  expect(colourAt('deep', 0)).toEqual([40, 26, 44]);
  expect(colourAt('amp', 0)).toEqual([60, 9, 18]);
});
