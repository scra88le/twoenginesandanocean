// Zonal budget data (docs/PROPOSALS-v2.md F7, F8): the JSON written by pipeline/src/pipeline/zonal.py
// for every climate frame (`clim/zonal/{frame}.json`) and every daily date (`zonal/{date}.json`).
// This file loads, validates and words it; every number is computed by the pipeline.
import type { Manifest } from './manifest';
import { tileUrl } from './manifest';
import type { Frame, Mode } from './modes';

export const NLAT = 360;

export interface TwoBox {
  r_tropics: number;
  r_poles: number;
  j_opt: number;
  t_tropics: number;
  t_poles: number;
  delta_t: number;
  g_max: number;
  j_obs: number;
  skt_tropics: number;
  skt_poles: number;
}

export interface ZonalGlobal {
  asr_toa: number;
  olr: number;
  imbalance: number;
  j_conv: number;
  carnot: number;
  diss_bl: number;
  diss_bl_pct: number;
  g_max_two_box?: number; // Year frame only
  // Year frame only, for the overview infographic (docs/PROPOSALS-v2.md F13). Each is absent if
  // the pipeline didn't have the field (`lw_up` and `asr_atm` need the `str` climatology).
  asr_sfc?: number;
  lw_up?: number;
  lh?: number;
  sh?: number;
  precip?: number; // mm day⁻¹
  t_skin?: number; // K
  t_r?: number; // K
  asr_atm?: number;
  pw_atm?: number; // PW, the largest poleward transport in either hemisphere
  pw_ocean?: number;
}

export interface Zonal {
  lat: number[]; // 360 cell centres, north first
  asr_toa: number[];
  olr: number[];
  net_toa: number[];
  skt: number[];
  // PW, northward positive, at the 361 cell edges. North first, like `lat`: index 0 is the north pole.
  transport_total: number[];
  transport_atm: number[];
  transport_ocean?: number[]; // Year frame only
  global: ZonalGlobal;
  two_box?: TwoBox; // Year frame only
  budget_residual?: { mean: number; rms: number; zonal_rms: number };
}

const CURVES = ['lat', 'asr_toa', 'olr', 'net_toa', 'skt'] as const;
const EDGES = ['transport_total', 'transport_atm', 'transport_ocean'] as const;
const GLOBALS = ['asr_toa', 'olr', 'imbalance', 'j_conv', 'carnot', 'diss_bl', 'diss_bl_pct'] as const;

const isNums = (v: unknown, n: number): v is number[] =>
  Array.isArray(v) && v.length === n && v.every((x) => typeof x === 'number' && Number.isFinite(x));

/** Check the shape of a zonal file; throws a message naming the first thing wrong. */
export function parseZonal(raw: unknown): Zonal {
  const z = raw as Record<string, unknown> | null;
  if (!z || typeof z !== 'object') throw new Error('zonal file is not an object');
  for (const k of CURVES) if (!isNums(z[k], NLAT)) throw new Error(`zonal ${k} must be ${NLAT} numbers`);
  for (const k of EDGES) {
    if (k === 'transport_ocean' && z[k] === undefined) continue;
    if (!isNums(z[k], NLAT + 1)) throw new Error(`zonal ${k} must be ${NLAT + 1} numbers`);
  }
  const g = z.global as Record<string, unknown> | undefined;
  if (!g || GLOBALS.some((k) => typeof g[k] !== 'number' || !Number.isFinite(g[k] as number))) {
    throw new Error('zonal global is incomplete');
  }
  return z as unknown as Zonal;
}

/**
 * Where the zonal file of what is on screen lives: the frame's file in Climate, the date's in
 * Today and Today vs normal. Null when it can't be named (no climatology, no date).
 */
export function zonalUrl(base: string, m: Manifest, mode: Mode, frame: Frame, date: string): string | null {
  if (mode === 'climate') {
    return m.clim ? tileUrl(base, m.clim.zonal ?? 'clim/zonal/{frame}.json', { frame }) : null;
  }
  return date ? `${base}/zonal/${date}.json` : null;
}

const cache = new Map<string, Promise<Zonal | null>>();

/** Fetch and cache one zonal file; null if it isn't published (daily files exist only for rebuilt dates). */
export function loadZonal(url: string, fetcher: typeof fetch = fetch): Promise<Zonal | null> {
  let p = cache.get(url);
  if (!p) {
    p = fetcher(url)
      .then(async (r) => (r.ok ? parseZonal(await r.json()) : null))
      .catch(() => null);
    cache.set(url, p);
    // a miss may be a date that is published a moment later, so don't keep it
    void p.then((z) => z || cache.delete(url));
  }
  return p;
}

/** A north-first array turned south-first, so x rises with latitude. */
const south = (a: number[]) => [...a].reverse();

/** An element of an array whose length the caller has checked. */
const at = (a: number[], i: number) => a[i] as number;

/** x of the chart: sin φ, so equal widths are equal areas of the sphere. */
export const sinLat = (latDeg: number) => Math.sin((latDeg * Math.PI) / 180);

export const LAT_TICKS = [-60, -30, 0, 30, 60];

/** The latitude label of a tick: "60°S", "0°", "40°N". */
export const latLabel = (lat: number) => (lat === 0 ? '0°' : `${Math.abs(lat)}°${lat < 0 ? 'S' : 'N'}`);

/** The 361 cell edges, south to north, as latitudes and as sin φ (the transport chart's x). */
export function edgeLats(lat: number[]): number[] {
  const step = at(lat, 0) - at(lat, 1); // 0.5, north first
  return [at(lat, 0) + step / 2, ...lat.map((l) => l - step / 2)].reverse();
}

export interface Shade {
  sign: 1 | -1; // +1 where sunlight absorbed exceeds heat radiated (surplus), -1 for a deficit
  x: number[];
  lo: number[]; // the lower curve of the band
  hi: number[]; // the upper
}

/**
 * The bands between two zonal curves, split where they cross (the crossing is interpolated),
 * for filling surplus and deficit. `x` and both curves have the same length.
 */
export function shadeBands(x: number[], asr: number[], olr: number[]): Shade[] {
  const out: Shade[] = [];
  let cur: Shade | null = null;
  const push = (sign: 1 | -1, xi: number, a: number, o: number) => {
    if (!cur || cur.sign !== sign) {
      cur = { sign, x: [], lo: [], hi: [] };
      out.push(cur);
    }
    cur.x.push(xi);
    cur.lo.push(Math.min(a, o));
    cur.hi.push(Math.max(a, o));
  };
  for (let i = 0; i < x.length; i++) {
    const d = at(asr, i) - at(olr, i);
    const sign: 1 | -1 = d >= 0 ? 1 : -1;
    if (i > 0) {
      const dp = at(asr, i - 1) - at(olr, i - 1);
      if ((dp >= 0) !== (d >= 0)) {
        const t = dp / (dp - d);
        const xc = at(x, i - 1) + t * (at(x, i) - at(x, i - 1));
        const v = at(asr, i - 1) + t * (at(asr, i) - at(asr, i - 1));
        push(dp >= 0 ? 1 : -1, xc, v, v); // close the previous band at the crossing
        push(sign, xc, v, v); // and open the next from it
      }
    }
    push(sign, at(x, i), at(asr, i), at(olr, i));
  }
  return out;
}

/** The latitudes (interpolated, south first) where absorbed sunlight and radiated heat cross. */
export function crossingLats(lat: number[], asr: number[], olr: number[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < lat.length; i++) {
    const a = at(asr, i - 1) - at(olr, i - 1);
    const b = at(asr, i) - at(olr, i);
    if (a !== 0 && b !== 0 && a > 0 !== b > 0) out.push(at(lat, i - 1) + (a / (a - b)) * (at(lat, i) - at(lat, i - 1)));
  }
  return out.sort((x, y) => x - y);
}

/** The peak northward transport in PW and the latitude of that edge, for either hemisphere's sign. */
export function peakTransport(edges: number[], lats: number[], sign: 1 | -1): { pw: number; lat: number } {
  let best = 0;
  for (let i = 1; i < edges.length; i++) if (at(edges, i) * sign > at(edges, best) * sign) best = i;
  return { pw: at(edges, best), lat: at(lats, best) };
}

const f0 = (v: number) => v.toFixed(0);
const f1 = (v: number) => v.toFixed(1);

/** The panel's one-line check of the two-box model; the Year frame only (`frame` null: a daily date). */
export function twoBoxText(z: Zonal | null, frame: Frame | null): string {
  if (frame === null) return 'The two-box maximum-power estimate is for the annual mean: see Climate mode, Year.';
  if (frame !== 'year') return 'The two-box maximum-power estimate is for the annual mean: choose the Year frame.';
  const t = z?.two_box;
  if (!t) return 'No two-box estimate for this frame.';
  const era = t.skt_tropics - t.skt_poles;
  return `Max-power prediction: J ≈ ${f0(t.j_opt)} W m⁻², ΔT ≈ ${f0(t.delta_t)} K. ERA5: J = ${f0(t.j_obs)} W m⁻², ΔT = ${f0(era)} K.`;
}

export interface StripItem {
  id: string;
  label: string; // plain words first
  symbol: string;
  value: string; // formatted, with its unit
  layer: string | null; // the layer whose (i) panel the tooltip links to
  formula: string;
}

/**
 * The global engine strip: the frame's area-weighted means, plain label first. `z` null gives
 * dashes; the two-box item is there in the Year frame only.
 */
export function stripItems(z: Zonal | null, frame: Frame | null): StripItem[] {
  const g = z?.global;
  const val = (v: number | undefined, unit: string, f = f1) => (v === undefined ? '—' : `${f(v)} ${unit}`);
  const items: StripItem[] = [
    { id: 'asr', label: 'Sunlight absorbed', symbol: '⟨ASR⟩', value: val(g?.asr_toa, 'W m⁻²'), layer: 'asr_toa',
      formula: 'Area-weighted mean of absorbed solar at the top of the atmosphere (tsr).' },
    { id: 'olr', label: 'Heat radiated to space', symbol: '⟨OLR⟩', value: val(g?.olr, 'W m⁻²'), layer: 'olr',
      formula: 'Area-weighted mean of outgoing longwave radiation, −ttr.' },
    { id: 'imb', label: 'Imbalance', symbol: '⟨ASR⟩ − ⟨OLR⟩', value: val(g?.imbalance, 'W m⁻²'), layer: 'net_toa',
      formula: 'Absorbed sunlight minus radiated heat; the net radiation at the top of the atmosphere.' },
    { id: 'conv', label: 'Heat lifted by convection', symbol: '⟨LE + H⟩', value: val(g?.j_conv, 'W m⁻²', f0), layer: 'j_conv',
      formula: 'Latent plus sensible heat flux from the surface, area-weighted mean.' },
    { id: 'carnot', label: 'Ceiling (Carnot)', symbol: '⟨η_C⟩', value: val(g?.carnot, '%'), layer: 'carnot',
      formula: 'η_C = (T_s − T_r) / T_s, with T_r the radiative temperature of the whole system.' },
  ];
  if (frame === 'year') {
    items.push({ id: 'twobox', label: 'Max power, two-box', symbol: 'G_max', value: val(g?.g_max_two_box, 'W m⁻²', (v) => v.toFixed(2)),
      layer: null, formula: 'G_max = (R_s,t − R_s,p)² / (16 b T_s,t): Kleidon’s two-box maximum power for the annual mean.' });
  }
  items.push({
    id: 'diss', label: 'Motion lost to friction near the ground', symbol: '⟨D_BL⟩',
    value: g ? `${g.diss_bl.toFixed(2)} W m⁻² (${g.diss_bl_pct.toFixed(1)} % of sunlight absorbed)` : '—',
    layer: 'diss_bl', formula: 'Area-weighted mean of boundary-layer dissipation (bld), and its share of ⟨ASR⟩.',
  });
  return items;
}

export interface PanelData {
  x: number[]; // sin φ of the 360 cell centres, south to north
  asr: number[];
  olr: number[];
  ex: number[]; // sin φ of the 361 cell edges, south to north
  total: number[]; // PW
  atm: number[];
  ocean: number[] | null; // Year frame only
}

/** What the two charts plot, ordered south to north so x rises. */
export function panelData(z: Zonal): PanelData {
  return {
    x: south(z.lat).map(sinLat),
    asr: south(z.asr_toa),
    olr: south(z.olr),
    ex: edgeLats(z.lat).map(sinLat),
    total: south(z.transport_total),
    atm: south(z.transport_atm),
    ocean: z.transport_ocean ? south(z.transport_ocean) : null,
  };
}

const lat0 = (lat: number) => latLabel(Math.round(lat));

/** The panel's text alternative: where the surplus lies and where transport peaks. */
export function summaryLines(z: Zonal): string[] {
  const out: string[] = [];
  const cross = crossingLats(z.lat, z.asr_toa, z.olr);
  const [first, second] = cross;
  if (cross.length === 2 && first !== undefined && second !== undefined) {
    const k = z.lat.findIndex((l) => l <= (first + second) / 2); // a cell between the crossings
    const surplusInside = at(z.asr_toa, k) > at(z.olr, k);
    out.push(
      surplusInside
        ? `Absorbed sunlight exceeds radiated heat between ${lat0(first)} and ${lat0(second)}; poleward of that it falls short.`
        : `Radiated heat exceeds absorbed sunlight between ${lat0(first)} and ${lat0(second)}.`,
    );
  } else if (cross.length) {
    out.push(`Absorbed sunlight and radiated heat cross at ${cross.map(lat0).join(', ')}.`);
  } else {
    out.push('Absorbed sunlight and radiated heat do not cross.');
  }
  const lats = edgeLats(z.lat);
  const rows: [string, number[]][] = [['total', south(z.transport_total)], ['atmosphere', south(z.transport_atm)]];
  if (z.transport_ocean) rows.push(['ocean', south(z.transport_ocean)]);
  for (const [name, e] of rows) {
    const n = peakTransport(e, lats, 1);
    const s = peakTransport(e, lats, -1);
    out.push(`Peak ${name} transport: ${n.pw.toFixed(1)} PW northward at ${lat0(n.lat)}, ${Math.abs(s.pw).toFixed(1)} PW southward at ${lat0(s.lat)}.`);
  }
  return out;
}
