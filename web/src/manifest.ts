// Types and loading for manifest.json, written by pipeline/src/pipeline/publish.py.
import type { EncodeRange } from './codes';
import type { OceanMeta } from './ocean';

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
  modes?: ('climate' | 'today' | 'anom')[]; // absent in manifests from before milestone 16
  default_mode?: 'climate' | 'today' | 'anom' | null;
  advanced?: boolean; // technical layers sit under "More layers" in the menu (absent before milestone 19)
  menu_order?: number;
  kind?: 'flow' | 'stock' | 'ratio' | null; // the human layers (milestone 25); null for the natural ones
  climate_label?: string | null; // what a human layer's Climate frames show: "2024 energy use"
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
  groups?: Record<string, { name: string; blurb: string }>; // absent before milestone 19
  layers: Record<string, LayerMeta>;
  points?: PointsMeta; // absent in manifests from before milestone 9
  series?: { file: string; magic: string };
  credits: string;
  ocean?: OceanMeta | null; // the ocean overlay (Copernicus Marine GLO12); absent until it is built
}

export interface ClimMeta {
  period: string; // "1991-2020"
  layers: string[];
  file: string; // clim/{MM}/{layer}.png
  series: string; // clim/series/{layer}/{tx}_{ty}.bin: 12 months x tile x tile codes
  frames?: string[]; // "01".."12", "year"
  year_file?: string; // clim/year/{layer}.png
  year_series?: string; // clim/year/series/{layer}/{tx}_{ty}.bin: one value per cell
  points?: string; // clim/points/{frame}/{tx}_{ty}.bin, the daily point-chunk layout
  zonal?: string; // clim/zonal/{frame}.json: zonal means, transport and global means
  uv_file?: string; // clim/{frame}/{layer}_uv.png: divergent flux and mean-flow vectors
  uv_layers?: string[]; // layers that have a climate uv file
  flux_ref?: number; // arrow reference (W m-1) shared by all frames: 98th percentile of |F|
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
  fields: string[]; // the 25 layers, then the extras
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

/** The climate map of a layer for a frame ("01".."12" or "year"). */
export function climUrl(base: string, clim: ClimMeta, frame: string, layer: string): string {
  if (frame === 'year') return tileUrl(base, clim.year_file ?? 'clim/year/{layer}.png', { layer });
  return tileUrl(base, clim.file, { MM: frame, layer });
}

/** The climate vector file of a layer (`flux_e` or a wind level) for a frame; null if none is published. */
export function climUvUrl(base: string, clim: ClimMeta | null | undefined, frame: string, layer: string): string | null {
  if (!clim?.uv_file || !clim.uv_layers?.includes(layer)) return null;
  return tileUrl(base, clim.uv_file, { frame, layer });
}
