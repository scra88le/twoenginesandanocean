import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { decodePng } from '../src/png';
import { scalarCodes, vectorCodes } from '../src/codes';

const fixture = (name: string) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url));

// Fixtures come from pipeline/scripts/make_web_fixtures.py, written with the real encoder.
describe('PNG decoding', () => {
  test('scalar RGB fixture decodes to exact codes', async () => {
    const png = await decodePng(fixture('scalar.png'));
    expect([png.width, png.height, png.channels]).toEqual([720, 360, 3]);
    const codes = scalarCodes(png);
    const points: [number, number][] = [[0, 0], [0, 719], [1, 5], [91, 17], [359, 719], [200, 300]];
    for (const [j, i] of points) {
      expect(codes[j * 720 + i]).toBe((j * 720 + i) % 65536);
    }
    let mismatches = 0;
    for (let j = 0; j < 360; j++)
      for (let i = 0; i < 720; i++) if (codes[j * 720 + i] !== (j * 720 + i) % 65536) mismatches++;
    expect(mismatches).toBe(0);
  });

  test('vector RGBA fixture keeps u where alpha is zero', async () => {
    const png = await decodePng(fixture('vector.png'));
    expect(png.channels).toBe(4);
    for (let k = 3; k < png.data.length; k += 4) expect(png.data[k]).toBe(0);
    const { u, v } = vectorCodes(png);
    let bad = 0;
    for (let j = 0; j < 360; j++)
      for (let i = 0; i < 720; i++) {
        const k = j * 720 + i;
        if (u[k] !== (i * 91 + j) % 65536 || v[k] !== (i % 256) << 8) bad++;
      }
    expect(bad).toBe(0);
  });

  test('rejects data that is not a PNG', async () => {
    await expect(decodePng(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9]))).rejects.toThrow(/PNG/);
  });

  test('scalarCodes rejects an RGBA image', async () => {
    const png = await decodePng(fixture('vector.png'));
    expect(() => scalarCodes(png)).toThrow(/RGB/);
  });
});
