import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { infoSections, maskLabel } from '../src/info';
import type { Manifest } from '../src/manifest';
import { menuGroups } from '../src/menu';

// The e2e fixture manifest is written by the real pipeline, so it has every layer's metadata.
const manifest = JSON.parse(
  readFileSync(new URL('../e2e/fixtures/data/manifest.json', import.meta.url), 'utf8'),
) as Manifest;

test('menu has the five groups of the site\'s title in order, with all 25 layers', () => {
  const groups = menuGroups(manifest);
  expect(groups.map((g) => g.name)).toEqual([
    'Engine one: surface to sky', 'Engine two: tropics to poles', 'The ocean', 'Water', 'Humans',
  ]);
  expect(groups.flatMap((g) => g.layers).length).toBe(25);
  expect(groups.map((g) => g.layers.length)).toEqual([8, 11, 1, 3, 2]);
});

test('each group has a one-line explanation', () => {
  for (const g of menuGroups(manifest)) {
    expect(g.blurb, g.name).not.toBe('');
    expect(g.blurb).not.toContain('\n');
  }
});

test('plain layers come first in each group, advanced ones after, both in the proposed order', () => {
  const [one, two, ocean, water, humans] = menuGroups(manifest);
  expect(one!.layers.map((l) => l.id)).toEqual(['asr_sfc', 'carnot', 'g_max', 'j_ratio', 'evap_frac', 'j_conv', 'lh', 'sh']);
  expect(one!.layers.filter((l) => l.advanced).map((l) => l.id)).toEqual(['j_conv', 'lh', 'sh']);
  expect(two!.layers.filter((l) => !l.advanced).map((l) => l.id)).toEqual(['net_toa', 'div_e', 'flux_e', 'ke_col', 'jet250']);
  expect(two!.layers.filter((l) => l.advanced).map((l) => l.id)).toEqual(['asr_toa', 'olr', 't_emit', 'diss_bl', 'wind10', 'wind100']);
  expect(ocean!.layers.map((l) => l.id)).toEqual(['net_sfc']);
  expect(water!.layers.map((l) => l.id)).toEqual(['precip', 'tcwv', 'p_lift']);
  expect(water!.layers.filter((l) => l.advanced).map((l) => l.id)).toEqual(['p_lift']);
  expect(humans!.layers.map((l) => l.id)).toEqual(['human_q', 'human_ratio']);
});

test('a manifest from before the regrouping still builds a menu, in its own order', () => {
  const old = structuredClone(manifest) as Manifest;
  delete old.groups;
  for (const l of Object.values(old.layers)) {
    delete l.advanced;
    delete l.menu_order;
  }
  const groups = menuGroups(old);
  expect(groups.flatMap((g) => g.layers).length).toBe(25);
  expect(groups.every((g) => g.blurb === '')).toBe(true);
  expect(groups.flatMap((g) => g.layers).every((l) => !l.advanced)).toBe(true);
});

test('only built layers are enabled', () => {
  const enabled = menuGroups(manifest).flatMap((g) => g.layers).filter((l) => l.enabled).map((l) => l.id);
  expect(enabled.sort()).toEqual([
    'asr_sfc', 'carnot', 'diss_bl', 'div_e', 'evap_frac', 'flux_e', 'j_ratio', 'jet250', 'ke_col', 'lh', 'net_sfc',
    'net_toa', 'precip', 'sh', 't_emit', 'wind10', 'wind100',
  ]);
});

test('each menu entry carries its one-line summary', () => {
  const olr = menuGroups(manifest).flatMap((g) => g.layers).find((l) => l.id === 'olr')!;
  expect(olr.title).toBe('Heat radiated to space, OLR');
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
