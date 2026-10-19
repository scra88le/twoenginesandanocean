// Wind helpers shared by the particle layer and the hover readout.
import { decodeValue, type EncodeRange } from './codes';
import { cellIndex } from './grid';
import type { Grid } from './manifest';

export const WIND_LEVELS = ['wind10', 'wind100', 'jet250'] as const;
export type WindLevel = (typeof WIND_LEVELS)[number];

export const LEVEL_LABELS: Record<WindLevel, string> = {
  wind10: '10 m',
  wind100: '100 m',
  jet250: '250 hPa',
};

export function isWindLevel(s: string | null | undefined): s is WindLevel {
  return (WIND_LEVELS as readonly string[]).includes(s ?? '');
}

/** u, v (m/s) in the cell containing a point; null outside the grid or where there's no data. */
export function windAt(
  u: Uint16Array, v: Uint16Array, enc: EncodeRange, grid: Grid, lng: number, lat: number,
): { u: number; v: number } | null {
  const cell = cellIndex(lng, lat, grid);
  if (!cell) return null;
  const k = cell.j * grid.nlon + cell.i;
  const x = decodeValue(u[k]!, enc);
  const y = decodeValue(v[k]!, enc);
  return Number.isFinite(x) && Number.isFinite(y) ? { u: x, v: y } : null;
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

/** The direction the wind blows *from*, as an 8-point compass name (meteorological convention). */
export function compassFrom(u: number, v: number): string {
  const deg = (Math.atan2(-u, -v) * 180) / Math.PI; // 0 = from the north, clockwise
  return COMPASS[Math.round(((deg + 360) % 360) / 45) % 8]!;
}

export function describeWind(w: { u: number; v: number }): string {
  const speed = Math.hypot(w.u, w.v);
  return speed < 0.05 ? 'calm' : `${speed.toFixed(1)} m/s from ${compassFrom(w.u, w.v)}`;
}

/** Particles for a canvas of this CSS size: one per 90 px², halved on narrow (phone) screens. */
export function particleCount(width: number, height: number): number {
  const n = (width * height) / 90;
  const scaled = width < 700 ? n / 2 : n;
  return Math.round(Math.min(32768, Math.max(1024, scaled)));
}

/** Speed on screen at the top of a level's colour range, in CSS px per second. */
export const PX_PER_S_AT_HI = 180;

/**
 * Mercator units moved per (m/s) of wind in `dt` seconds. Screen speed is proportional to
 * wind speed and independent of zoom and latitude, so it reads as a speed, not as the map's
 * stretching; `speedHi` (the top of the level's colour range) sets the scale per level.
 */
export function mercatorStep(speedHi: number, zoom: number, dt: number): number {
  const worldPx = 512 * 2 ** zoom;
  return ((PX_PER_S_AT_HI / speedHi) * dt) / worldPx;
}
