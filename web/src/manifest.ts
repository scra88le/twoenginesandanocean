// Types and loading for manifest.json, written by pipeline/src/pipeline/publish.py.
import type { EncodeRange } from './codes';

export interface Grid {
  nlon: number;
  nlat: number;
  lon0: number;
  lat0: number;
  step: number;
}

export interface LayerInfo {
  summary: string;
  source: string;
  formula: string;
  sign: string;
  meaning: string;
  caveats: string;
  mask: string | null;
  anomaly: string; // how the anomaly is made, or why there is none
}

export interface LayerMeta {
  title: string;
  group: number;
  group_name: string;
  units: string;
  colour: string;
  display: [number, number] | 'auto';
  log: boolean;
  centre: number | null;
  vector: boolean;
  anomaly: boolean; // has an anomaly variant
  anomaly_display: [number, number] | null;
  anomaly_colour: string | null;
  encode: EncodeRange;
  uv_encode: EncodeRange | null;
  anomaly_encode: EncodeRange | null;
  hatch_zero: boolean;
  info: LayerInfo;
}

export interface Manifest {
  version: number;
  built_at: string;
  dates: string[];
  built_layers: string[];
  grid: Grid;
  codes: { nodata: number; masked: number; first_valid: number };
  files: { field: string; uv: string; anomaly: string };
  clim?: ClimMeta | null; // null until the climatology job has run
  layers: Record<string, LayerMeta>;
  points?: PointsMeta; // absent in manifests from before milestone 9
  series?: { file: string; magic: string };
  credits: string;
}

export interface ClimMeta {
  period: string; // "1991-2020"
  layers: string[];
  file: string; // clim/{MM}/{layer}.png
  series: string; // clim/series/{layer}/{tx}_{ty}.bin: 12 months x tile x tile codes
}

/** A readout-only quantity in the point chunks (not a map layer). */
export interface ExtraMeta {
  title: string;
  units: string;
  encode: EncodeRange;
}

export interface PointsMeta {
  file: string;
  tile: number;
  fields: string[]; // the 24 layers, then the extras
  extras: Record<string, ExtraMeta>;
}

export async function loadManifest(base: string): Promise<Manifest> {
  const res = await fetch(`${base}/manifest.json`, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`manifest.json: HTTP ${res.status}`);
  return (await res.json()) as Manifest;
}

export function fieldUrl(base: string, m: Manifest, date: string, layer: string): string {
  return `${base}/${m.files.field.replace('{date}', date).replace('{layer}', layer)}`;
}

export function uvUrl(base: string, m: Manifest, date: string, layer: string): string {
  return `${base}/${m.files.uv.replace('{date}', date).replace('{layer}', layer)}`;
}

export function tileUrl(base: string, template: string, vars: Record<string, string | number>): string {
  return `${base}/${template.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k]))}`;
}

export function anomalyUrl(base: string, m: Manifest, date: string, layer: string): string {
  return tileUrl(base, m.files.anomaly, { date, layer });
}

/** Whether the anomaly of a layer can be shown: it has one and the climatology is published. */
export function hasAnomaly(m: Manifest, layer: string): boolean {
  return !!m.layers[layer]?.anomaly && !!m.clim?.layers.includes(layer);
}
