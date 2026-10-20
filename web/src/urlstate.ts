// URL state: the query string holds what the visitor is looking at, so a copied URL restores
// layer, date, view, overlays, anomaly and pinned point. Reading validates everything (a stale
// or hand-edited link falls back to defaults instead of breaking); writing keeps the order of
// the keys fixed and leaves parameters it doesn't own (like ?debug) alone.
import type { Manifest } from './manifest';
import type { ParticleChoice } from './overlays';
import { isWindLevel } from './wind';

export interface ViewState {
  layer: string;
  date: string;
  anomaly: boolean;
  particles: ParticleChoice;
  arrows: boolean;
  center: [number, number]; // lng, lat
  zoom: number;
  pin: [number, number] | null; // lng, lat of the pinned cell
}

export const DEFAULT_LAYER = 'net_toa';
export const DEFAULT_CENTER: [number, number] = [0.25, 20];
export const DEFAULT_ZOOM = 1.4;
export const DEFAULT_PARTICLES: ParticleChoice = { on: true, level: 'wind10' };

const MAX_LAT = 85.05;
const MAX_ZOOM = 22;
// Keys written in this order; `tour` is dropped (it only opens the tour, once).
const OWNED = ['layer', 'date', 'center', 'zoom', 'particles', 'anom', 'arrows', 'pin', 'tour'];

/** "lng,lat" -> numbers, or null if it isn't two finite numbers. */
export function parseCenter(text: string | null): [number, number] | null {
  const parts = text?.split(',');
  if (parts?.length !== 2) return null;
  const [lng, lat] = parts.map((p) => (p.trim() === '' ? NaN : Number(p)));
  return Number.isFinite(lng) && Number.isFinite(lat) ? [lng!, lat!] : null;
}

/** Longitude wrapped into -180..180 (the map can be panned past the date line). */
export const wrapLng = (lng: number) => ((((lng + 180) % 360) + 360) % 360) - 180;

export function parseParticles(text: string | null): ParticleChoice {
  if (text === 'off') return { on: false, level: DEFAULT_PARTICLES.level };
  return { on: true, level: isWindLevel(text) ? text : DEFAULT_PARTICLES.level };
}

/** The view state a URL asks for, with anything invalid replaced by a default. */
export function readState(params: URLSearchParams, m: Manifest): ViewState {
  const wantedDate = params.get('date');
  const date = wantedDate && m.dates.includes(wantedDate) ? wantedDate : (m.dates.at(-1) ?? '');
  const wanted = params.get('layer');
  const layer =
    wanted && m.layers[wanted] && m.built_layers.includes(wanted)
      ? wanted
      : m.built_layers.includes(DEFAULT_LAYER)
        ? DEFAULT_LAYER
        : (m.built_layers[0] ?? DEFAULT_LAYER);
  const center = parseCenter(params.get('center'));
  const zoomText = params.get('zoom');
  const zoom = zoomText === null || zoomText.trim() === '' ? NaN : Number(zoomText); // not "" -> 0
  const pin = parseCenter(params.get('pin'));
  return {
    layer,
    date,
    anomaly: params.get('anom') === '1',
    particles: parseParticles(params.get('particles')),
    arrows: params.get('arrows') === '1',
    center: center && Math.abs(center[1]) <= MAX_LAT ? [wrapLng(center[0]), center[1]] : DEFAULT_CENTER,
    zoom: Number.isFinite(zoom) && zoom >= 0 && zoom <= MAX_ZOOM ? zoom : DEFAULT_ZOOM,
    pin: pin && Math.abs(pin[1]) <= 90 ? [wrapLng(pin[0]), pin[1]] : null,
  };
}

/** The query string (without "?") for a state, keeping other parameters of `current`. */
export function stateQuery(current: string | URLSearchParams, s: ViewState): string {
  const out = new URLSearchParams();
  out.set('layer', s.layer);
  out.set('date', s.date);
  out.set('center', `${wrapLng(s.center[0]).toFixed(2)},${s.center[1].toFixed(2)}`);
  out.set('zoom', s.zoom.toFixed(2));
  out.set('particles', s.particles.on ? s.particles.level : 'off');
  if (s.anomaly) out.set('anom', '1');
  if (s.arrows) out.set('arrows', '1');
  if (s.pin) out.set('pin', `${s.pin[0].toFixed(2)},${s.pin[1].toFixed(2)}`);
  for (const [k, v] of new URLSearchParams(current)) if (!OWNED.includes(k)) out.append(k, v);
  return out.toString().replace(/%2C/g, ',');
}
