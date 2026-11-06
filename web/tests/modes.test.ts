import { expect, test } from 'vitest';
import { climUvUrl, type ClimMeta, type Manifest } from '../src/manifest';
import {
  FRAMES, availableModes, defaultMode, meanFlowText, playFrame, resolveMode, stepFrame, timescaleText,
} from '../src/modes';

type M = ('climate' | 'today' | 'anom')[];
const layer = (modes: M, default_mode: 'climate' | 'today' | null, anomaly = true) =>
  ({ modes, default_mode, anomaly }) as unknown as Manifest['layers'][string];
const all: M = ['climate', 'today', 'anom'];
const manifest = (clim: boolean): Manifest =>
  ({
    clim: clim ? { layers: ['net_toa', 'olr', 'j_ratio'], period: '1991-2020' } : null,
    layers: {
      net_toa: layer(all, 'climate'),
      olr: layer(all, 'today'),
      j_ratio: layer(['climate'], 'climate'),
      wind10: layer(['today'], 'today', false),
      human_q: layer([], null, false),
      old: { anomaly: true } as Manifest['layers'][string],
    },
  }) as unknown as Manifest;

test('every layer opens in its default mode', () => {
  const m = manifest(true);
  expect(defaultMode(m, 'net_toa')).toBe('climate');
  expect(defaultMode(m, 'olr')).toBe('today');
  expect(defaultMode(m, 'j_ratio')).toBe('climate');
  expect(defaultMode(m, 'wind10')).toBe('today');
});

test('a layer that offers the wanted mode keeps it', () => {
  const m = manifest(true);
  expect(resolveMode(m, 'olr', 'anom')).toEqual({ mode: 'anom', switched: false });
  expect(resolveMode(m, 'net_toa', 'today')).toEqual({ mode: 'today', switched: false });
});

test('a layer that does not offer the wanted mode switches to its default', () => {
  const m = manifest(true);
  expect(resolveMode(m, 'j_ratio', 'today')).toEqual({ mode: 'climate', switched: true });
  expect(resolveMode(m, 'wind10', 'climate')).toEqual({ mode: 'today', switched: true });
  expect(resolveMode(m, 'wind10', 'anom')).toEqual({ mode: 'today', switched: true });
});

test('no wanted mode means the default, without a switch note', () => {
  expect(resolveMode(manifest(true), 'net_toa', null)).toEqual({ mode: 'climate', switched: false });
});

test('without a published climatology the climate-based modes are unavailable', () => {
  const m = manifest(false);
  expect(availableModes(m, 'net_toa')).toEqual(['today']);
  expect(defaultMode(m, 'net_toa')).toBe('today');
  expect(availableModes(m, 'j_ratio')).toEqual(['today']); // its daily data, better than nothing
  expect(defaultMode(m, 'j_ratio')).toBe('today');
});

test('a layer the climatology lacks offers Today only', () => {
  const m = manifest(true);
  m.layers.t_emit = layer(all, 'today');
  expect(availableModes(m, 't_emit')).toEqual(['today']);
});

test('old manifests without modes fall back to Today and the anomaly', () => {
  expect(availableModes(manifest(false), 'old')).toEqual(['today']);
  const m = manifest(true);
  m.clim!.layers.push('old');
  expect(availableModes(m, 'old')).toEqual(['today', 'anom']);
});

test('human layers have no mode', () => {
  expect(availableModes(manifest(true), 'human_q')).toEqual([]);
});

test('the legend names the timescale', () => {
  expect(timescaleText('climate', '07', '2026-10-17', '1991-2020')).toBe('1991–2020 mean, July');
  expect(timescaleText('climate', 'year', '2026-10-17', '1991-2020')).toBe('Annual mean, 1991–2020');
  expect(timescaleText('today', '07', '2026-10-17', '1991-2020')).toBe('2026-10-17');
  expect(timescaleText('anom', '07', '2026-10-17', '1991-2020')).toBe('2026-10-17 minus the October 1991–2020 mean');
  // the human layers: present-day typical months, not a 1991-2020 mean
  expect(timescaleText('climate', '07', '2026-10-17', '1991-2020', '2024 energy use')).toBe('2024 energy use, typical July');
  expect(timescaleText('climate', 'year', '2026-10-17', '1991-2020', '2024 energy use')).toBe('2024 energy use, annual mean');
  expect(timescaleText('today', '07', '2026-10-17', '1991-2020', '2024 energy use')).toBe('2026-10-17');
});

test('there are 13 frames, stepping stops at the ends, and play loops January to December', () => {
  expect(FRAMES).toHaveLength(13);
  expect(stepFrame('01', -1)).toBe('01');
  expect(stepFrame('12', 1)).toBe('year');
  expect(stepFrame('year', 1)).toBe('year');
  expect(stepFrame('year', -1)).toBe('12');
  expect(playFrame('01')).toBe('02');
  expect(playFrame('12')).toBe('01');
  expect(playFrame('year')).toBe('01');
});

test('overlay captions name the frame after the period', () => {
  expect(meanFlowText('01')).toBe('January');
  expect(meanFlowText('year')).toBe('annual mean');
});

test('climate vector files are found only for layers that have them', () => {
  const clim = {
    uv_file: 'clim/{frame}/{layer}_uv.png',
    uv_layers: ['flux_e', 'wind10'],
  } as unknown as ClimMeta;
  expect(climUvUrl('/data', clim, '07', 'wind10')).toBe('/data/clim/07/wind10_uv.png');
  expect(climUvUrl('/data', clim, 'year', 'flux_e')).toBe('/data/clim/year/flux_e_uv.png');
  expect(climUvUrl('/data', clim, '07', 'jet250')).toBeNull();
  expect(climUvUrl('/data', null, '07', 'wind10')).toBeNull();
  expect(climUvUrl('/data', { ...clim, uv_file: undefined }, '07', 'wind10')).toBeNull();
});
