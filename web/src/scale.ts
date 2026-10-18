// Display scaling: value -> position 0..1 on the colour scale. The raster shader applies the
// same mapping to the same parameters (see layers/raster.ts).
import type { LayerMeta } from './manifest';

export interface DisplayScale {
  lo: number; // layer units
  hi: number;
  log: boolean;
  centre: number | null; // maps to 0.5
}

const space = (v: number, log: boolean) => (log ? Math.log10(v) : v);

export function toT(value: number, s: DisplayScale): number {
  const x = space(value, s.log);
  const lo = space(s.lo, s.log);
  const hi = space(s.hi, s.log);
  let t: number;
  if (s.centre === null) {
    t = (x - lo) / (hi - lo);
  } else {
    const c = space(s.centre, s.log);
    t = x < c ? 0.5 * (x - lo) / (c - lo) : 0.5 + 0.5 * (x - c) / (hi - c);
  }
  return Math.min(1, Math.max(0, t));
}

function percentile(sorted: Float64Array, q: number): number {
  const pos = (sorted.length - 1) * q;
  const k = Math.floor(pos);
  const f = pos - k;
  return k + 1 < sorted.length ? sorted[k]! * (1 - f) + sorted[k + 1]! * f : sorted[k]!;
}

/** The day's 2nd-98th percentile, symmetric about zero for diverging scales. */
export function autoRange(values: Float64Array, diverging: boolean): [number, number] {
  const finite = values.filter((v) => Number.isFinite(v)).sort();
  if (finite.length === 0) return [0, 1];
  const lo = percentile(finite, 0.02);
  const hi = percentile(finite, 0.98);
  if (!diverging) return [lo, hi];
  const m = Math.max(Math.abs(lo), Math.abs(hi));
  return [-m, m];
}

export function displayScale(meta: LayerMeta, values?: Float64Array): DisplayScale {
  const [lo, hi] =
    meta.display === 'auto'
      ? autoRange(values ?? new Float64Array(), meta.centre === 0)
      : meta.display;
  return { lo, hi, log: meta.log, centre: meta.centre };
}

const SUPERSCRIPT: Record<string, string> = {
  '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
};
export const superscript = (n: number) => [...String(n)].map((c) => SUPERSCRIPT[c] ?? c).join('');

export interface Tick {
  value: number;
  label: string;
  t: number;
}

function niceStep(span: number, target: number): number {
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  return (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
}

export function ticks(s: DisplayScale, target = 5): Tick[] {
  const out: Tick[] = [];
  if (s.log) {
    for (let e = Math.ceil(Math.log10(s.lo) - 1e-9); e <= Math.floor(Math.log10(s.hi) + 1e-9); e++) {
      out.push({ value: 10 ** e, label: `10${superscript(e)}`, t: toT(10 ** e, s) });
    }
    return out;
  }
  const step = niceStep(s.hi - s.lo, target - 1);
  for (let v = Math.ceil(s.lo / step - 1e-9) * step; v <= s.hi + 1e-9 * step; v += step) {
    const value = Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12));
    out.push({ value, label: String(value).replace('-', '−'), t: toT(value, s) });
  }
  return out;
}
