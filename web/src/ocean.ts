// The ocean overlay: the two limbs of the Atlantic overturning (AMOC) as coloured particles.
// The data and the numbers come from pipeline/src/pipeline/ocean.py (Copernicus Marine GLO12);
// this module only finds the files, picks what to draw and words the captions.
import type { EncodeRange } from './codes';
import type { LayerInfo } from './manifest';

export const OCEAN_LIMBS = ['amoc_upper', 'amoc_deep'] as const;
export type OceanLimb = (typeof OCEAN_LIMBS)[number];
export type OceanLimbs = 'both' | 'upper' | 'deep';
export type OceanAvg = 'mean' | 'daily';

export interface OceanChoice {
  on: boolean;
  limbs: OceanLimbs;
  avg: OceanAvg;
}

export const DEFAULT_OCEAN: OceanChoice = { on: false, limbs: 'both', avg: 'mean' };

export interface LimbMeta {
  title: string;
  colour: string; // hex
  top_m: number;
  bottom_m: number | null; // null: the sea floor
  units: string; // transport, m2 s-1
  uv_units: string; // depth-mean velocity, m s-1
  display: [number, number];
  encode: EncodeRange; // transport magnitude (log)
  uv_encode: EncodeRange; // velocity components
  speed_hi: number; // m s-1 drawn at the particle layer's top screen speed
  density_ref: number; // m2 s-1 at and above which every particle is drawn
}

export interface Section {
  psi_max_sv: number;
  z_max_m: number;
  amoc_upper_sv: number;
  amoc_deep_sv: number;
}

/** The latitude-depth section's grid: latitude bins and the model's depth levels. */
export interface SectionGrid {
  lat0: number;
  dlat: number;
  n_lat: number;
  depth_edges_m: number[]; // nz + 1 edges, 0 at the surface
  unit_sv: number; // the file's integers are multiples of this
}

export interface OceanDate {
  window_days: number;
  section?: { daily: boolean; mean: boolean };
  daily: Section;
  mean: Section | null; // null until enough days of the 30-day window are in
}

export interface OceanMeta {
  product: string;
  dataset: string;
  split_m: number;
  window_days: number;
  section: { lat: number; lon: [number, number] };
  files: { field: string; uv: string; section?: string; avg: Record<OceanAvg, string> };
  section_grid?: SectionGrid | null;
  limbs: Record<OceanLimb, LimbMeta>;
  dates: Record<string, OceanDate>;
  info: LayerInfo;
  credit: string;
}

export const LIMB_CHOICES: Record<OceanLimbs, { label: string; limbs: OceanLimb[] }> = {
  both: { label: 'Both limbs', limbs: ['amoc_upper', 'amoc_deep'] },
  upper: { label: 'Upper limb (warm, north)', limbs: ['amoc_upper'] },
  deep: { label: 'Deep limb (cold, south)', limbs: ['amoc_deep'] },
};

export const AVG_LABELS: Record<OceanAvg, string> = { mean: '30-day mean', daily: 'Daily' };

export function isOceanLimbs(s: string | null | undefined): s is OceanLimbs {
  return s === 'both' || s === 'upper' || s === 'deep';
}

/** The file of one limb: its transport (`uv` false) or its velocity (`uv` true). */
export function oceanUrl(base: string, o: OceanMeta, date: string, limb: OceanLimb, avg: OceanAvg, uv: boolean): string {
  const template = uv ? o.files.uv : o.files.field;
  const vars: Record<string, string> = { date, limb, avg: o.files.avg[avg] };
  return `${base}/${template.replace(/\{(\w+)\}/g, (_, k: string) => vars[k] ?? '')}`;
}

/** What a date offers: the daily field, and the 30-day mean once its window has enough days. */
export function oceanAvailable(o: OceanMeta | null | undefined, date: string): Record<OceanAvg, boolean> {
  const d = o?.dates[date];
  return { daily: !!d, mean: !!d?.mean };
}

/** The averaging to draw: the one asked for, else the other one the date has; null if neither. */
export function resolveAvg(o: OceanMeta | null | undefined, date: string, wanted: OceanAvg): OceanAvg | null {
  const a = oceanAvailable(o, date);
  if (a[wanted]) return wanted;
  const other: OceanAvg = wanted === 'mean' ? 'daily' : 'mean';
  return a[other] ? other : null;
}

/** "#f08a5d" -> [0.94, 0.54, 0.36] for a shader uniform. */
export function hexToRgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!m) return [1, 1, 1];
  return [1, 2, 3].map((k) => parseInt(m[k]!, 16) / 255) as [number, number, number];
}

const sv = (x: number) => `${Math.abs(x).toFixed(1)} Sv`;
const metres = (x: number) => `${Math.round(x).toLocaleString('en-GB')} m`;

/** The legend line: what is drawn, over which period, and the 26.5° N figures. */
export function oceanCaption(o: OceanMeta, date: string, choice: OceanChoice, avg: OceanAvg): string {
  const entry = o.dates[date]!;
  const s = (avg === 'mean' ? entry.mean : entry.daily) ?? entry.daily;
  const when = avg === 'mean' ? `${o.window_days}-day mean to ${date}` : `daily mean, ${date}`;
  const lat = `${o.section.lat}° N`;
  const parts = LIMB_CHOICES[choice.limbs].limbs.map((l) =>
    l === 'amoc_upper'
      ? `upper limb ${sv(s.amoc_upper_sv)} ${s.amoc_upper_sv >= 0 ? 'north' : 'south'}`
      : `deep limb ${sv(s.amoc_deep_sv)} ${s.amoc_deep_sv >= 0 ? 'north' : 'south'}`,
  );
  return (
    `Ocean overturning (GLO12, ${when}): across ${lat}, ${parts.join(', ')}; ` +
    `AMOC ${sv(s.psi_max_sv)} at ${metres(s.z_max_m)}`
  );
}

/** The limb's depth range for the legend, e.g. "0–1,100 m" or "below 1,100 m". */
export function limbDepth(l: LimbMeta): string {
  return l.bottom_m === null ? `below ${metres(l.top_m)}` : `${metres(l.top_m).replace(' m', '')}–${metres(l.bottom_m)}`;
}

/** The ocean overlay as an info-panel entry, in the shape the info panel reads. */
export function oceanInfoMeta(o: OceanMeta) {
  return {
    title: 'Ocean overturning (AMOC)',
    units: `${o.limbs.amoc_upper.units} (transport), ${o.limbs.amoc_upper.uv_units} (particles)`,
    info: o.info,
  };
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

/** The direction a current flows *toward*, as an 8-point compass name (oceanographic convention). */
export function compassTo(u: number, v: number): string {
  const deg = (Math.atan2(u, v) * 180) / Math.PI; // 0 = toward the north, clockwise
  return COMPASS[Math.round(((deg + 360) % 360) / 45) % 8]!;
}

/** Hover text for one limb in one cell: how much water it carries and where it goes. */
export function describeLimb(name: string, transport: number, u: number, v: number): string {
  if (!Number.isFinite(transport) || !Number.isFinite(u) || !Number.isFinite(v)) return `${name}: none here`;
  const speed = Math.hypot(u, v);
  const t = transport >= 100 ? transport.toFixed(0) : transport >= 10 ? transport.toFixed(1) : transport.toFixed(2);
  const where = speed < 0.0005 ? 'still' : `${speed < 0.1 ? speed.toFixed(3) : speed.toFixed(2)} m/s toward ${compassTo(u, v)}`;
  return `${name}: ${t} m²/s, ${where}`;
}

export interface AmocTrend {
  dates: string[];
  t: number[]; // seconds since the epoch (UTC midnight), for the chart's time axis
  daily: number[]; // AMOC strength across the section, Sv
  mean: (number | null)[]; // 30-day mean's strength; null until the window is in
}

/** The overturning strength at the section for every date with ocean data, oldest first. */
export function amocTrend(o: OceanMeta): AmocTrend {
  const dates = Object.keys(o.dates).sort();
  return {
    dates,
    t: dates.map((d) => Date.parse(`${d}T00:00:00Z`) / 1000),
    daily: dates.map((d) => o.dates[d]!.daily.psi_max_sv),
    mean: dates.map((d) => o.dates[d]!.mean?.psi_max_sv ?? null),
  };
}

/** The trend as sentences, for the text fold-out and the chart's accessible name. */
export function amocTrendText(tr: AmocTrend): string[] {
  const n = tr.dates.length;
  if (!n) return [];
  const last = n - 1;
  const lines = [`${n} day${n === 1 ? '' : 's'} of ocean currents, ${tr.dates[0]} to ${tr.dates[last]}.`];
  lines.push(`Daily AMOC strength on ${tr.dates[last]}: ${tr.daily[last]!.toFixed(1)} Sv.`);
  const m = tr.mean[last];
  if (m != null) lines.push(`30-day mean to ${tr.dates[last]}: ${m.toFixed(1)} Sv.`);
  const means = tr.mean.filter((x): x is number => x != null);
  if (means.length > 1) {
    const first = means[0]!;
    const change = means[means.length - 1]! - first;
    lines.push(`The 30-day mean moved ${change >= 0 ? 'up' : 'down'} ${Math.abs(change).toFixed(1)} Sv over the period shown (from ${first.toFixed(1)} Sv).`);
  }
  return lines;
}

/** The streamfunction on the latitude-depth section: psi[k][j] in Sv at the bottom edge of
 * level k and latitude bin j, NaN where the basin has no water. */
export interface SectionField {
  upper: number[]; // the upper limb's net northward transport at each latitude, Sv (NaN: dry); empty if absent
  deep: number[]; // the deep limb's, Sv
  psi: number[][];
  lat: number[];
  edges: number[];
}

/** Which averaging has a section for the date, or null. */
export function sectionAvg(o: OceanMeta | null | undefined, date: string, wanted: OceanAvg): OceanAvg | null {
  const s = o?.dates[date]?.section;
  if (!o?.section_grid || !o.files.section || !s) return null;
  if (s[wanted]) return wanted;
  const other: OceanAvg = wanted === 'mean' ? 'daily' : 'mean';
  return s[other] ? other : null;
}

export function sectionUrl(base: string, o: OceanMeta, date: string, avg: OceanAvg): string {
  const vars: Record<string, string> = { date, avg: o.files.avg[avg] };
  return `${base}/${o.files.section!.replace(/\{(\w+)\}/g, (_, k: string) => vars[k] ?? '')}`;
}

/** Check and unpack a section file against the manifest's grid. */
export function parseSection(raw: unknown, grid: SectionGrid): SectionField {
  const body = raw as { psi?: unknown; upper_sv?: unknown; deep_sv?: unknown } | null;
  const rows = body?.psi;
  const belt = (x: unknown): number[] => {
    if (x === undefined) return [];
    if (!Array.isArray(x) || x.length !== grid.n_lat) throw new Error('ocean section: wrong number of latitudes');
    return x.map((v) => (typeof v === 'number' ? v : NaN));
  };
  const nz = grid.depth_edges_m.length - 1;
  if (!Array.isArray(rows) || rows.length !== nz) throw new Error('ocean section: wrong number of levels');
  const psi = rows.map((r: unknown) => {
    if (!Array.isArray(r) || r.length !== grid.n_lat) throw new Error('ocean section: wrong number of latitudes');
    return r.map((x) => (typeof x === 'number' ? x * grid.unit_sv : NaN));
  });
  return { upper: belt(body?.upper_sv), deep: belt(body?.deep_sv), psi, lat: Array.from({ length: grid.n_lat }, (_, j) => grid.lat0 + j * grid.dlat), edges: grid.depth_edges_m };
}

/** The overturning strength at each latitude: the largest psi down the column, and its depth. */
export function sectionStrength(sec: SectionField): { sv: number[]; z: number[] } {
  const sv: number[] = [];
  const z: number[] = [];
  for (let j = 0; j < sec.lat.length; j++) {
    let best = NaN;
    let at = NaN;
    for (let k = 0; k < sec.psi.length; k++) {
      const v = sec.psi[k]![j]!;
      if (Number.isFinite(v) && !(v <= best)) {
        best = v;
        at = sec.edges[k + 1]!;
      }
    }
    sv.push(best);
    z.push(at);
  }
  return { sv, z };
}

const NEUTRAL: [number, number, number] = [27, 31, 39];
const WARM = [240, 138, 93];
const COLD = [111, 182, 242];

/** Colour of a streamfunction value: warm for the clockwise (northward-above) overturning, cold for
 * the reverse, dark at zero; `vmax` Sv is the full colour. */
export function psiColour(v: number, vmax: number): [number, number, number] {
  if (!Number.isFinite(v)) return [0, 0, 0];
  const t = Math.min(1, Math.abs(v) / vmax);
  const to = v >= 0 ? WARM : COLD;
  return [0, 1, 2].map((c) => Math.round(NEUTRAL[c]! + (to[c]! - NEUTRAL[c]!) * t)) as [number, number, number];
}

/** The section as sentences, for the fold-out and the heatmap's accessible name. */
export function sectionText(sec: SectionField, o: OceanMeta): string[] {
  const { sv, z } = sectionStrength(sec);
  let jMax = -1;
  sv.forEach((x, j) => {
    if (Number.isFinite(x) && (jMax < 0 || x > sv[jMax]!)) jMax = j;
  });
  if (jMax < 0) return ['No water in the section.'];
  const at = (lat: number) => {
    const j = Math.round((lat - sec.lat[0]!) / (sec.lat[1]! - sec.lat[0]!));
    return sv[j] != null && Number.isFinite(sv[j]!) ? `${sv[j]!.toFixed(1)} Sv at ${Math.round(z[j]!).toLocaleString('en-GB')} m` : null;
  };
  const lines = [`Strongest overturning: ${sv[jMax]!.toFixed(1)} Sv at ${Math.abs(sec.lat[jMax]!).toFixed(1)}° ${sec.lat[jMax]! < 0 ? 'S' : 'N'}, ${Math.round(z[jMax]!).toLocaleString('en-GB')} m deep.`];
  for (const lat of [-34, 0, o.section.lat, 45]) {
    const a = at(lat);
    if (a) lines.push(`${lat === 0 ? 'The equator' : `${Math.abs(lat)}° ${lat < 0 ? 'S' : 'N'}`}: ${a}.`);
  }
  return lines;
}

export interface BeltBin {
  lat: number; // bin centre
  upper: number; // Sv, northward positive; NaN if the bin has no water
  deep: number;
}

/** The limbs' transport by latitude, averaged into bins `step` degrees wide: a display average
 * of the pipeline's per-latitude sums, which smooths what is left of the day-to-day wiggle. */
export function beltBins(sec: SectionField, step = 5): BeltBin[] {
  if (!sec.upper.length) return [];
  const lo = Math.round(sec.lat[0]!);
  const hi = Math.round(sec.lat[sec.lat.length - 1]!);
  const bins: BeltBin[] = [];
  for (let a = lo; a < hi; a += step) {
    const idx = sec.lat.map((l, j) => (l >= a - 1e-6 && l < a + step - 1e-6 ? j : -1)).filter((j) => j >= 0);
    const mean = (xs: number[]) => {
      const ok = idx.map((j) => xs[j]!).filter((x) => Number.isFinite(x));
      return ok.length >= idx.length / 2 ? ok.reduce((t, x) => t + x, 0) / ok.length : NaN;
    };
    bins.push({ lat: a + step / 2, upper: mean(sec.upper), deep: mean(sec.deep) });
  }
  return bins;
}

const dir = (x: number) => (x >= 0 ? 'north' : 'south');
const latName = (lat: number) => (lat === 0 ? 'The equator' : `${Math.abs(lat)}° ${lat < 0 ? 'S' : 'N'}`);

/** The belt as sentences: what each limb carries, and which way, at a few latitudes. */
export function beltText(sec: SectionField, o: OceanMeta): string[] {
  if (!sec.upper.length) return [];
  const lines: string[] = [];
  for (const lat of [-30, 0, o.section.lat, 45]) {
    const j = Math.round((lat - sec.lat[0]!) / (sec.lat[1]! - sec.lat[0]!));
    const u = sec.upper[j];
    const d = sec.deep[j];
    if (u == null || d == null || !Number.isFinite(u) || !Number.isFinite(d)) continue;
    lines.push(`${latName(lat)}: upper limb ${Math.abs(u).toFixed(1)} Sv ${dir(u)}, deep limb ${Math.abs(d).toFixed(1)} Sv ${dir(d)}.`);
  }
  return lines;
}
