import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { MASKED, NODATA } from '../src/codes';
import { flowText, flowValues, flowWidths } from '../src/energyflow';
import type { Manifest } from '../src/manifest';
import { READOUT_ROWS } from '../src/readout';

const manifest = JSON.parse(
  readFileSync(new URL('../e2e/fixtures/data/manifest.json', import.meta.url), 'utf8'),
) as Manifest;

/** The code of a value in a layer's own packing. */
const code = (id: string, v: number) => {
  const e = manifest.layers[id]!.encode;
  return Math.round((v - e.offset) / e.scale) + 2;
};
const codes = (over: Record<string, number> = {}) =>
  new Map(Object.entries({ asr_sfc: code('asr_sfc', 150), lh: code('lh', 80), sh: code('sh', 20), net_sfc: code('net_sfc', 10), ...over }));

test('the flows at a cell: infrared is what is left of the published surface budget', () => {
  const f = flowValues(manifest, codes())!;
  expect(f.sun).toBeCloseTo(150, 0);
  expect(f.le).toBeCloseTo(80, 0);
  expect(f.h).toBeCloseTo(20, 0);
  expect(f.net).toBeCloseTo(10, 0);
  expect(f.ir).toBeCloseTo(150 - 80 - 20 - 10, 0); // net_sfc = asr_sfc - lw_up - lh - sh
  expect(f.sun - f.ir - f.le - f.h).toBeCloseTo(f.net, 9);
});

test('no diagram when a layer is unbuilt, masked or has no data', () => {
  expect(flowValues(manifest, codes({ lh: MASKED }))).toBeNull();
  expect(flowValues(manifest, codes({ sh: NODATA }))).toBeNull();
  expect(flowValues(manifest, new Map([['asr_sfc', code('asr_sfc', 150)]]))).toBeNull();
  const unbuilt = { ...manifest, built_layers: manifest.built_layers.filter((l) => l !== 'net_sfc') };
  expect(flowValues(unbuilt, codes())).toBeNull();
});

test('arrow widths share one scale: proportional, the biggest flow at the maximum, none under the minimum', () => {
  const w = flowWidths({ sun: 200, le: 100, h: 50, ir: 20, net: -0.1 }, 20, 1.5);
  expect(w.sun).toBe(20);
  expect(w.le).toBe(10);
  expect(w.h).toBe(5);
  expect(w.ir).toBe(2);
  expect(w.net).toBe(1.5);
});

test('the text says everything the picture does, with the direction of the net flow', () => {
  const t = flowText({ sun: 164, le: 84, h: 17, ir: 58, net: 5 });
  expect(t).toBe(
    'At the surface: sunlight absorbed 164 W m⁻². Heat leaving: latent 84 W m⁻², sensible 17 W m⁻², infrared 58 W m⁻². Net heat into the surface: 5 W m⁻².',
  );
  expect(flowText({ sun: 100, le: 80, h: 30, ir: 40, net: -50 })).toContain('Net heat out of the surface: 50 W m⁻².');
});

test('readout rows name each quantity in plain words first, the symbol after a comma', () => {
  const names = Object.fromEntries(READOUT_ROWS.flatMap((r) => r.items));
  expect(names.j_conv).toBe('Heat lifted by convection, LE + H');
  expect(names.j_ratio).toBe('Share of the optimum, r_J');
  for (const n of Object.values(names)) expect(n.split(',')[0], n).toMatch(/[A-Za-z]{4,}/); // the part before the comma is a word, never a bare symbol
});
