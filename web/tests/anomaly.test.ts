import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { anomalyNote, anomalyView, monthName } from '../src/anomaly';
import { infoSections } from '../src/info';
import { hasAnomaly, type Manifest } from '../src/manifest';
import { displayScale, toT } from '../src/scale';

const manifest = JSON.parse(
  readFileSync(new URL('../e2e/fixtures/data/manifest.json', import.meta.url), 'utf8'),
) as Manifest;

test('the anomaly view is linear, centred on zero, with the fixed anomaly range', () => {
  const precip = manifest.layers.precip!; // a log layer
  const view = anomalyView(precip);
  expect(view.title).toBe('Precipitation, anomaly');
  expect(view.log).toBe(false);
  expect(view.centre).toBe(0);
  expect(view.colour).toBe('BrBG');
  expect(view.encode).toEqual(precip.anomaly_encode);
  const s = displayScale(view);
  expect(s.lo).toBe(-s.hi);
  expect(toT(0, s)).toBe(0.5);
  expect(anomalyView(manifest.layers.carnot!).hatch_zero).toBe(false);
});

test('vector and human layers have no anomaly view', () => {
  for (const id of ['wind10', 'wind100', 'jet250', 'flux_e', 'human_q']) {
    expect(manifest.layers[id]!.anomaly).toBe(false);
    expect(() => anomalyView(manifest.layers[id]!)).toThrow(/no anomaly/);
  }
});

test('an anomaly needs the layer to have one and the climatology to be published', () => {
  expect(hasAnomaly(manifest, 't_emit')).toBe(true); // the fixture has a climatology
  expect(hasAnomaly(manifest, 'wind10')).toBe(false);
  expect(hasAnomaly({ ...manifest, clim: null }, 't_emit')).toBe(false);
});

test('notes and the info panel explain the anomaly', () => {
  expect(monthName('2026-08-05')).toBe('August');
  expect(anomalyNote('1991-2020', '2026-10-01')).toBe('Difference from the 1991–2020 October mean');
  const labels = (id: string) => infoSections(manifest.layers[id]!, '').map((s) => s.label);
  expect(labels('carnot')).toContain('Anomaly');
  const text = infoSections(manifest.layers.wind10!, '').find((s) => s.label === 'Anomaly')!.text;
  expect(text).toMatch(/^No anomaly/);
});
