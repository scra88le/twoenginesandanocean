import { readdirSync, readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import type { Manifest } from '../src/manifest';
import {
  CHIPS, FAMILIES, PARTS, SEEN_KEY, SLOTS, fluxWidths, markSeen, shouldAutoShow, slotValues,
} from '../src/overview';
import { parseCards } from '../src/story';
import { parseZonal, type Zonal } from '../src/zonal';

const data = new URL('../e2e/fixtures/data/', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('manifest.json', data), 'utf8')) as Manifest;
const year = parseZonal(JSON.parse(readFileSync(new URL('clim/zonal/year.json', data), 'utf8'))) as Zonal;
const svg = readFileSync(new URL('../src/overview/desktop.svg', import.meta.url), 'utf8');

const dir = new URL('../../story/', import.meta.url);
const steps = parseCards(
  Object.fromEntries(
    readdirSync(dir).filter((f) => f.endsWith('.md')).map((f) => [`../../story/${f}`, readFileSync(new URL(f, dir), 'utf8')]),
  ),
);

// Vitest runs without a DOM, so the SVG is read as text: every opening tag with its attributes.
const attrs = (name: string) => [...svg.matchAll(new RegExp(`\\b${name}="([^"]*)"`, 'g'))].map((m) => m[1]!);
const elements = [...svg.matchAll(/<g class="ov-el"([^>]*)>([\s\S]*?)<\/g>/g)].map((m) => ({
  attrs: m[1]!,
  body: m[2]!,
  get: (k: string) => new RegExp(`${k}="([^"]*)"`).exec(m[1]!)?.[1],
}));
const slots = [...new Set(attrs('data-slot'))];

test('the graphic has ten clickable elements, each with a label, a title, a description and a step', () => {
  expect(elements).toHaveLength(10);
  for (const e of elements) {
    expect(e.get('data-el'), e.attrs).toBeTruthy();
    expect(e.get('data-label'), e.attrs).toBeTruthy();
    expect(e.attrs).toContain('tabindex="0"');
    expect(e.attrs).toContain('role="link"');
    expect(e.body).toMatch(/<title><\/title>/);
    expect(e.body).toMatch(/<desc>[^<]+<\/desc>/);
  }
  expect(new Set(elements.map((e) => e.get('data-el'))).size).toBe(10);
});

test('every data-step points to an existing tour card, and the ten steps are each used once', () => {
  const ids = steps.map((s) => s.id.slice(0, 2));
  const used = elements.map((e) => e.get('data-step')!);
  for (const n of used) expect(ids, `step ${n}`).toContain(n);
  expect([...used].sort()).toEqual(['01', '02', '03', '04', '05', '06', '07', '08', '09', '10']);
});

test('every data-part is one of the three parts, and every part has an element', () => {
  for (const p of attrs('data-part')) expect(PARTS as readonly string[]).toContain(p);
  for (const part of PARTS) expect(elements.some((e) => e.get('data-part') === part), part).toBe(true);
  expect(CHIPS.map((c) => c.id)).toEqual(['all', ...PARTS]);
});

test('the elements open the steps of the proposal table', () => {
  const step = Object.fromEntries(elements.map((e) => [e.get('data-el'), e.get('data-step')]));
  expect(step).toEqual({
    toa: '01', 'surface-sun': '02', ceiling: '03', convection: '04', split: '05',
    surplus: '06', 'air-transport': '07', friction: '08', 'ocean-store': '09', 'ocean-transport': '10',
  });
  // the step's layer is the one the table names
  const layer = (n: string) => steps.find((s) => s.id.startsWith(`${n}-`))!.layer;
  expect(['01', '02', '03', '04', '05', '06', '07', '08', '09', '10'].map(layer)).toEqual([
    'net_toa', 'asr_sfc', 'carnot', 'j_ratio', 'evap_frac', 'net_toa', 'div_e', 'ke_col', 'net_sfc', 'net_sfc',
  ]);
});

test('every data-slot is a known slot, and the fixture year file fills all of them', () => {
  expect(slots.length).toBeGreaterThanOrEqual(15);
  const values = slotValues(year);
  for (const s of slots) {
    expect(Object.keys(SLOTS), s).toContain(s);
    expect(values[s], s).not.toBeNull();
    expect(values[s]!.text, s).not.toBe('');
    expect(values[s]!.exact, s).not.toBe('');
  }
  // and nothing in SLOTS is unused by the graphic
  for (const k of Object.keys(SLOTS)) expect(slots, k).toContain(k);
});

test('without a climatology every slot is null, so the graphic shows dashes', () => {
  const values = slotValues(null);
  for (const s of slots) expect(values[s], s).toBeNull();
  const partial = slotValues({ ...year, global: { ...year.global, lw_up: undefined } });
  expect(partial.lw_up).toBeNull();
  expect(partial.asr_toa).not.toBeNull();
});

test('values are rounded for reading and exact in the tooltip', () => {
  const g = { ...year.global, asr_toa: 242.6976, carnot: 11.2466, t_r: 255.778, t_skin: 288.2927, pw_ocean: 2.064, precip: 2.9288 };
  const v = slotValues({ ...year, global: g });
  expect(v.asr_toa).toEqual({ text: '≈ 243 W m⁻²', exact: '242.70 W m⁻²' });
  expect(v.carnot).toEqual({ text: '≈ 11 %', exact: '11.25 %' });
  expect(v.t_r!.text).toBe('256 K (−17 °C)');
  expect(v.t_skin!.text).toBe('288 K (15 °C)');
  expect(v.pw_ocean!.text).toBe('up to 2.1 PW');
  expect(v.precip!.text).toBe('≈ 2.9 mm day⁻¹');
});

test('slots that name a layer name one the manifest has', () => {
  const layerSlots = ['asr_toa', 'olr', 'asr_sfc', 'j_conv', 'lh', 'sh', 'precip', 'carnot', 'diss_bl'];
  for (const s of layerSlots) {
    expect(slots, s).toContain(s);
    expect(Object.keys(manifest.layers), s).toContain(s);
  }
  // the rest are not layers: they come from the zonal file's own block
  for (const s of slots.filter((x) => !layerSlots.includes(x))) expect(s in year.global, s).toBe(true);
});

test('arrow widths are proportional within a unit family, and each family has its own scale', () => {
  const w = fluxWidths({ ...year.global, asr_toa: 240, olr: 120, asr_sfc: 60, lw_up: 30, j_conv: 24, pw_atm: 5, pw_ocean: 2 }, 20, 2);
  expect(w.asr_toa).toBe(20);
  expect(w.olr).toBe(10);
  expect(w.asr_sfc).toBe(5);
  expect(w.pw_atm).toBe(20); // PW has its own scale
  expect(w.pw_ocean).toBe(8);
  expect(w.j_conv).toBe(2); // never thinner than the minimum
  expect(fluxWidths(undefined)).toEqual({});
  expect(fluxWidths({ ...year.global, pw_atm: undefined }).pw_atm).toBeUndefined();
});

test('every arrow in the graphic belongs to a family and carries the right family attribute', () => {
  const lines = [...svg.matchAll(/data-flux="([^"]+)" data-family="([^"]+)"/g)];
  expect(lines.length).toBeGreaterThanOrEqual(7);
  for (const [, flux, family] of lines) expect(FAMILIES[family!], flux).toContain(flux);
});

test('the SVG has no hard-coded numbers in its slots and no scripts or event handlers', () => {
  for (const m of svg.matchAll(/<tspan[^>]*data-slot[^>]*>([^<]*)<\/tspan>/g)) expect(m[1]).toBe('—');
  expect(svg).not.toMatch(/<script|\son[a-z]+=/i);
});

// ---- first visit -------------------------------------------------------------------------

const q = (s: string) => new URLSearchParams(s);
const stored = (v: string | null) => () => v;
const throws = () => {
  throw new Error('storage is blocked');
};

test('a visitor who has not seen it gets the overview; one who has does not', () => {
  expect(shouldAutoShow(q(''), stored(null))).toBe(true);
  expect(shouldAutoShow(q(''), stored('1'))).toBe(false);
  expect(shouldAutoShow(q('layer=t_emit&date=2026-10-01&pin=0,0'), stored(null))).toBe(true); // deep links still get it
});

test('blocked storage shows it, once per load', () => {
  expect(shouldAutoShow(q(''), throws)).toBe(true);
});

test('?tour and ?overview=0 suppress it; ?overview=1 always opens it', () => {
  expect(shouldAutoShow(q('tour=3'), stored(null))).toBe(false);
  expect(shouldAutoShow(q('overview=0'), stored(null))).toBe(false);
  expect(shouldAutoShow(q('overview=1'), stored('1'))).toBe(true);
  expect(shouldAutoShow(q('overview=1'), throws)).toBe(true);
  expect(shouldAutoShow(q('overview=1&tour=2'), stored('1'))).toBe(true);
});

test('dismissal is remembered, and a refusing store is not an error', () => {
  const set: [string, string][] = [];
  markSeen({ setItem: (k, v) => void set.push([k, v]) });
  expect(set).toEqual([[SEEN_KEY, '1']]);
  expect(SEEN_KEY).toBe('ehe.overview.seen');
  expect(() => markSeen({ setItem: throws })).not.toThrow();
});
