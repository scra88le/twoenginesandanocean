import { expect, test, vi } from 'vitest';
import type { Manifest } from '../src/manifest';
import {
  crossingLats, edgeLats, latLabel, loadZonal, parseZonal, peakTransport, shadeBands, sinLat,
  stripItems, summaryLines, panelData, twoBoxText, zonalUrl, type Shade, type Zonal,
} from '../src/zonal';

const n = (k: number, v = 1) => Array.from({ length: k }, () => v);
const lat = Array.from({ length: 360 }, (_, i) => 89.75 - 0.5 * i);
const make = (year: boolean): Zonal =>
  ({
    lat, asr_toa: n(360, 240), olr: n(360, 239), net_toa: n(360, 1), skt: n(360, 285),
    transport_total: n(361, 0), transport_atm: n(361, 0),
    ...(year ? { transport_ocean: n(361, 0) } : {}),
    global: { asr_toa: 242.7, olr: 242.2, imbalance: 0.49, j_conv: 100.9, carnot: 11.25, diss_bl: 2.354, diss_bl_pct: 0.97, ...(year ? { g_max_two_box: 1.4466 } : {}) },
    ...(year ? { two_box: { r_tropics: 304.6, r_poles: 180.8, j_opt: 30.95, t_tropics: 305.2, t_poles: 276.7, delta_t: 28.53, g_max: 1.4466, j_obs: 40.75, skt_tropics: 298.85, skt_poles: 277.73 } } : {}),
  }) as Zonal;

const m = { clim: { period: '1991-2020', layers: [], zonal: 'clim/zonal/{frame}.json' } } as unknown as Manifest;

test('the file is the frame in Climate and the date in Today and Today vs normal', () => {
  expect(zonalUrl('/d', m, 'climate', '07', '2026-10-01')).toBe('/d/clim/zonal/07.json');
  expect(zonalUrl('/d', m, 'climate', 'year', '')).toBe('/d/clim/zonal/year.json');
  expect(zonalUrl('/d', m, 'today', '07', '2026-10-01')).toBe('/d/zonal/2026-10-01.json');
  expect(zonalUrl('/d', m, 'anom', '07', '2026-10-01')).toBe('/d/zonal/2026-10-01.json');
  expect(zonalUrl('/d', { clim: null } as Manifest, 'climate', 'year', '')).toBeNull();
  expect(zonalUrl('/d', m, 'today', 'year', '')).toBeNull();
});

test('parseZonal accepts a good file with or without the Year extras, and names what is wrong', () => {
  expect(parseZonal(make(true)).two_box?.j_opt).toBe(30.95);
  expect(parseZonal(make(false)).transport_ocean).toBeUndefined();
  expect(() => parseZonal({ ...make(false), olr: n(359) })).toThrow(/olr/);
  expect(() => parseZonal({ ...make(false), transport_atm: n(360) })).toThrow(/transport_atm/);
  expect(() => parseZonal({ ...make(false), global: { asr_toa: 1 } })).toThrow(/global/);
  expect(() => parseZonal(null)).toThrow();
});

test('loadZonal caches hits, returns null for a miss or bad file, and retries a miss', async () => {
  const ok = vi.fn(async () => ({ ok: true, json: async () => make(false) }) as Response);
  expect((await loadZonal('/a.json', ok))?.global.olr).toBe(242.2);
  await loadZonal('/a.json', ok);
  expect(ok).toHaveBeenCalledTimes(1);
  const miss = vi.fn(async () => ({ ok: false }) as Response);
  expect(await loadZonal('/b.json', miss)).toBeNull();
  await Promise.resolve();
  await loadZonal('/b.json', miss);
  expect(miss).toHaveBeenCalledTimes(2);
  const bad = async () => ({ ok: true, json: async () => ({}) }) as Response;
  expect(await loadZonal('/c.json', bad)).toBeNull();
});

test('x is linear in sin φ and ticks are worded by hemisphere', () => {
  expect(sinLat(90)).toBeCloseTo(1);
  expect(sinLat(30)).toBeCloseTo(0.5);
  expect(sinLat(-30)).toBeCloseTo(-0.5);
  expect([latLabel(-60), latLabel(0), latLabel(40)]).toEqual(['60°S', '0°', '40°N']);
});

test('edges run south to north from -90 to 90', () => {
  const e = edgeLats(lat);
  expect(e).toHaveLength(361);
  expect(e[0]).toBe(-90);
  expect(e[360]).toBe(90);
  expect(e[180]).toBe(0);
});

test('shade bands split where the curves cross, at the interpolated point', () => {
  const x = [0, 1, 2, 3];
  const b = shadeBands(x, [5, 5, 1, 1], [3, 3, 3, 3]);
  expect(b.map((s) => s.sign)).toEqual([1, -1]);
  const [s0, s1] = b as [Shade, Shade];
  expect(s0.x).toEqual([0, 1, 1.5]);
  expect(s1.x).toEqual([1.5, 2, 3]);
  expect(s0.lo[0]).toBe(3);
  expect(s0.hi[0]).toBe(5);
  expect(s1.lo[1]).toBe(1);
  expect(s1.hi[1]).toBe(3);
  expect(s0.lo[2]).toBeCloseTo(s0.hi[2] as number); // pinched at the crossing
  expect(shadeBands([0, 1], [2, 2], [1, 1])).toHaveLength(1);
});

test('crossing latitudes are interpolated and sorted', () => {
  const l = [10, 0, -10, -20];
  expect(crossingLats(l, [1, 1, -1, -1], [0, 0, 0, 0])).toEqual([-5]);
  expect(crossingLats(l, [1, 1, 1, 1], [0, 0, 0, 0])).toEqual([]);
});

test('the peak transport takes the largest value of the wanted sign', () => {
  const e = [0, 2, 5, 1, -3, -6, 0];
  const l = [-90, -60, -30, 0, 30, 60, 90];
  expect(peakTransport(e, l, 1)).toEqual({ pw: 5, lat: -30 });
  expect(peakTransport(e, l, -1)).toEqual({ pw: -6, lat: 60 });
});

test('the two-box line is for the Year frame only', () => {
  expect(twoBoxText(make(true), 'year')).toBe('Max-power prediction: J ≈ 31 W m⁻², ΔT ≈ 29 K. ERA5: J = 41 W m⁻², ΔT = 21 K.');
  expect(twoBoxText(make(true), '07')).toMatch(/annual mean/);
  expect(twoBoxText(make(false), 'year')).toMatch(/No two-box/);
  expect(twoBoxText(null, 'year')).toMatch(/No two-box/);
  expect(twoBoxText(make(true), null)).toMatch(/Climate mode, Year/);
});

test('the strip words each global mean, adds the two-box item in Year only, and dashes a missing file', () => {
  const year = stripItems(make(true), 'year');
  expect(year.map((i) => i.id)).toEqual(['asr', 'olr', 'imb', 'conv', 'carnot', 'twobox', 'diss']);
  const v = (id: string) => year.find((i) => i.id === id);
  expect(v('asr')).toMatchObject({ label: 'Sunlight absorbed', value: '242.7 W m⁻²', layer: 'asr_toa' });
  expect(v('conv')?.value).toBe('101 W m⁻²');
  expect(v('carnot')?.value).toBe('11.3 %');
  expect(v('twobox')?.value).toBe('1.45 W m⁻²');
  expect(v('diss')?.value).toBe('2.35 W m⁻² (1.0 % of sunlight absorbed)');
  const month = stripItems(make(false), '07');
  expect(month.some((i) => i.id === 'twobox')).toBe(false);
  expect(stripItems(null, 'year').every((i) => i.value === '—')).toBe(true);
  expect(stripItems(make(true), null).some((i) => i.id === 'twobox')).toBe(false); // a daily date
  expect(stripItems(null, 'year').every((i) => i.formula && i.symbol && i.label)).toBe(true);
});

test('panel data runs south to north, including the north-first transport, and the text names the peaks', () => {
  const z = make(true);
  z.asr_toa = lat.map((l) => 300 * Math.cos((l * Math.PI) / 180));
  z.olr = n(360, 200);
  // north first, northward positive: the northern hemisphere carries heat north (index 0 is the pole)
  z.transport_total = Array.from({ length: 361 }, (_, i) => 5 * Math.sin(((i / 360) * 2 - 1) * Math.PI * 0.99) * -1);
  z.transport_ocean = n(361, 0.5);
  const d = panelData(z);
  expect(d.x[0]).toBeLessThan(d.x[359] as number);
  expect(d.ex).toHaveLength(361);
  expect(d.asr[180]).toBeGreaterThan(d.asr[0] as number);
  expect(d.ocean).toHaveLength(361);
  expect(d.total[0]).toBeLessThan(0); // south pole end: southward in the south
  expect(d.total[300]).toBeGreaterThan(0); // northward in the north
  expect(panelData(make(false)).ocean).toBeNull();
  const lines = summaryLines(z);
  expect(lines[0]).toMatch(/exceeds radiated heat between 4\d°S and 4\d°N/);
  const peak = lines.find((l) => l.startsWith('Peak total transport'))!;
  expect(peak).toMatch(/PW northward at \d+°N/);
  expect(peak).toMatch(/PW southward at \d+°S/);
  expect(lines.some((l) => l.startsWith('Peak ocean'))).toBe(true);
  expect(summaryLines(make(false))[0]).toMatch(/do not cross|cross at/);
});
