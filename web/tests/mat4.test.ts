import { expect, test } from 'vitest';
import { clipToMercator, invert } from '../src/mat4';

function multiply(a: ArrayLike<number>, b: ArrayLike<number>): number[] {
  const out = new Array<number>(16).fill(0);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) out[c * 4 + r]! += a[k * 4 + r]! * b[c * 4 + k]!;
  return out;
}

// A perspective camera looking straight down at the mercator plane, like MapLibre's at pitch 0:
// scale 4 about (0.5, 0.4), then a perspective divide with the plane at w = 2.
const m = [8, 0, 0, 0, 0, -8, 0.3, 0, 0, 0, 0.5, 0, -8, 6.4, 0.1, 2].map((x, k) => (k === 15 || k === 3 ? x : x * 2));

test('invert gives the inverse', () => {
  const inv = invert(m)!;
  const id = multiply(m, inv);
  id.forEach((x, k) => expect(x).toBeCloseTo(k % 5 === 0 ? 1 : 0, 12));
  expect(invert(new Array(16).fill(0))).toBeNull();
});

test('clipToMercator finds the map point under a clip position, beyond the world edge too', () => {
  const inv = invert(m)!;
  for (const [x, y] of [[0.5, 0.4], [0.1, -0.3], [1.7, 1.2]] as const) {
    const w = m[3]! * x + m[7]! * y + m[15]!;
    const cx = (m[0]! * x + m[4]! * y + m[12]!) / w;
    const cy = (m[1]! * x + m[5]! * y + m[13]!) / w;
    const [mx, my] = clipToMercator(inv, cx, cy);
    expect(mx).toBeCloseTo(x, 9);
    expect(my).toBeCloseTo(y, 9);
  }
});
