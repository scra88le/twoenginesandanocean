// Timescale modes (docs/PROPOSALS-v2.md F1): Climate (1991-2020 means, 12 months and a Year
// frame), Today (the daily layers) and Today vs normal (the anomaly). Which a layer offers
// comes from the manifest's `modes`; this file only resolves and words them.
import { monthName } from './anomaly';
import type { Manifest } from './manifest';

export type Mode = 'climate' | 'today' | 'anom';
export const MODES: Mode[] = ['climate', 'today', 'anom'];
export const MODE_LABELS: Record<Mode, string> = {
  climate: 'Climate',
  today: 'Today',
  anom: 'Today vs normal',
};

export const FRAMES = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12', 'year'] as const;
export type Frame = (typeof FRAMES)[number];
export const DEFAULT_FRAME: Frame = 'year';

export const isMode = (s: string | null): s is Mode => MODES.includes(s as Mode);
export const isFrame = (s: string | null): s is Frame => FRAMES.includes(s as Frame);

/**
 * The modes a layer can be shown in right now: the manifest's list, less the climate-based
 * ones while that layer has no published climatology. Manifests from before `modes` fall
 * back to Today, plus the anomaly where there is one.
 */
export function availableModes(m: Manifest, layer: string): Mode[] {
  const meta = m.layers[layer];
  if (!meta) return [];
  const listed: Mode[] = meta.modes ?? (meta.anomaly ? ['today', 'anom'] : ['today']);
  if (!listed.length) return []; // the human layers
  const hasClim = !!m.clim?.layers.includes(layer);
  const ok = listed.filter((x) => x === 'today' || hasClim);
  return ok.length ? ok : ['today']; // a Climate-only layer still has its daily data
}

/** The mode a layer opens in: its default if that is available, else Today. */
export function defaultMode(m: Manifest, layer: string): Mode {
  const avail = availableModes(m, layer);
  const d = m.layers[layer]?.default_mode;
  if (d && avail.includes(d)) return d;
  return avail.includes('today') ? 'today' : (avail[0] ?? 'today');
}

export interface Resolved {
  mode: Mode;
  switched: boolean; // the layer doesn't offer the wanted mode, so its default was used
}

/** Selecting a layer (or a mode) never changes the mode unless the layer can't show it. */
export function resolveMode(m: Manifest, layer: string, wanted: Mode | null): Resolved {
  if (wanted && availableModes(m, layer).includes(wanted)) return { mode: wanted, switched: false };
  return { mode: defaultMode(m, layer), switched: wanted !== null };
}

/** The word for one frame: "July" or "Annual mean". */
export const frameName = (f: Frame) => (f === 'year' ? 'Annual mean' : monthName(`2001-${f}-01`));

/** What the legend says the map shows, e.g. "1991–2020 mean, July" or "2026-10-17". */
export function timescaleText(mode: Mode, frame: Frame, date: string, period: string): string {
  const p = period.replace('-', '–');
  if (mode === 'climate') return frame === 'year' ? `Annual mean, ${p}` : `${p} mean, ${frameName(frame)}`;
  if (mode === 'anom') return `${date} minus the ${monthName(date)} ${p} mean`;
  return date;
}

/** One line when a layer was switched to a mode other than the one asked for. */
export function switchNote(mode: Mode): string {
  if (mode === 'climate') return "Shown as the 1991–2020 average: daily values aren't meaningful for this layer.";
  if (mode === 'today') return "Shown for the day: this layer has no climate or anomaly view.";
  return 'Shown as the difference from the 1991–2020 mean.';
}

/** The frame a step of `delta` reaches: arrow keys and the step buttons stop at the ends. */
export function stepFrame(f: Frame, delta: number): Frame {
  const i = Math.min(FRAMES.length - 1, Math.max(0, FRAMES.indexOf(f) + delta));
  return FRAMES[i]!;
}

/** Play cycles January to December and loops; it skips Year, and a Year start begins in January. */
export function playFrame(f: Frame): Frame {
  const i = FRAMES.indexOf(f);
  return i >= 11 ? FRAMES[0]! : FRAMES[i + 1]!;
}

/** The month frame to show for a date (the Today -> Climate switch keeps the season). */
export const frameOfDate = (date: string): Frame => date.slice(5, 7) as Frame;
