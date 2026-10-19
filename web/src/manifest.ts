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
  anomaly: boolean;
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
  files: { field: string; uv: string };
  layers: Record<string, LayerMeta>;
  credits: string;
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
