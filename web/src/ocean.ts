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

export interface OceanDate {
  window_days: number;
  daily: Section;
  mean: Section | null; // null until enough days of the 30-day window are in
}

export interface OceanMeta {
  product: string;
  dataset: string;
  split_m: number;
  window_days: number;
  section: { lat: number; lon: [number, number] };
  files: { field: string; uv: string; avg: Record<OceanAvg, string> };
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
