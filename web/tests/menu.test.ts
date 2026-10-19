import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { infoSections, maskLabel } from '../src/info';
import type { Manifest } from '../src/manifest';
import { menuGroups } from '../src/menu';

// The e2e fixture manifest is written by the real pipeline, so it has every layer's metadata.
const manifest = JSON.parse(
  readFileSync(new URL('../e2e/fixtures/data/manifest.json', import.meta.url), 'utf8'),
) as Manifest;

test('menu has the 9 story groups in order, with all 24 layers', () => {
  const groups = menuGroups(manifest);
  expect(groups.map((g) => g.name)).toEqual([
    'Fuel', 'Exhaust', 'Limits', 'Max power', 'Surface split', 'Output', 'Water', 'Transport', 'Humans',
  ]);
  expect(groups.flatMap((g) => g.layers).length).toBe(24);
  expect(groups[0]!.layers.map((l) => l.id)).toEqual(['asr_toa', 'asr_sfc', 'net_toa']);
});

test('only built layers are enabled', () => {
  const enabled = menuGroups(manifest).flatMap((g) => g.layers).filter((l) => l.enabled).map((l) => l.id);
  expect(enabled.sort()).toEqual([
    'carnot', 'diss_bl', 'div_e', 'evap_frac', 'flux_e', 'j_ratio', 'jet250', 'net_toa', 'precip', 't_emit',
    'wind10', 'wind100',
  ]);
});

test('each menu entry carries its one-line summary', () => {
  const olr = menuGroups(manifest).flatMap((g) => g.layers).find((l) => l.id === 'olr')!;
  expect(olr.title).toBe('Outgoing longwave');
  expect(olr.summary).toBe(manifest.layers.olr!.info.summary);
});

test('info sections cover source, units, sign, formula, meaning, caveats, anomaly and credit', () => {
  const s = infoSections(manifest.layers.g_max!, manifest.credits);
  expect(s.map((x) => x.label)).toEqual([
    'Source', 'Units', 'Sign convention', 'Formula', 'What it means for the heat engine', 'Caveats',
    'Grey cells', 'Anomaly', 'Data credit',
  ]);
  expect(s.find((x) => x.label === 'Units')!.text).toBe('W m⁻²');
});

test('layers without a mask have no grey-cells section', () => {
  const labels = infoSections(manifest.layers.olr!, manifest.credits).map((x) => x.label);
  expect(labels).not.toContain('Grey cells');
});

test('mask label is the first clause', () => {
  expect(maskLabel('Ocean and sea ice: the model ignores storage.')).toBe('Ocean and sea ice');
  expect(maskLabel('Where LE + H is below 10 W m⁻². More text.')).toBe('Where LE + H is below 10 W m⁻²');
});
