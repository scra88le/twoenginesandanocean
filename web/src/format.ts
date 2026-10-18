import type { EncodeRange } from './codes';
import { superscript } from './scale';

export const prettyUnits = (units: string) =>
  units.replace(/(\S)-(\d)/g, (_, c: string, d: string) => `${c}⁻${superscript(Number(d))}`);

const minus = (s: string) => s.replace('-', '−');

/** Fewest decimals that show the resolution exactly (0.25 -> 2, 0.2 -> 1, 1 -> 0), at most 4. */
function decimalsFor(step: number): number {
  for (let d = 0; d < 4; d++) {
    const scaled = step * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-9 * Math.max(1, scaled)) return d;
  }
  return 4;
}

/** A value for display, with precision from the layer's resolution. */
export function formatValue(v: number, units: string, enc: EncodeRange): string {
  if (!Number.isFinite(v)) return 'no data';
  const u = prettyUnits(units);
  let text: string;
  if (Math.abs(v) >= 1e5) {
    const [m, e] = v.toExponential(2).split('e');
    text = `${minus(m!)} × 10${superscript(Number(e))}`;
  } else if (enc.log) {
    text = minus(String(Number(v.toPrecision(3))));
  } else {
    text = minus(v.toFixed(decimalsFor(enc.scale)));
  }
  const celsius = units === 'K' ? ` (${minus((v - 273.15).toFixed(1))} °C)` : '';
  return `${text} ${u}${celsius}`;
}

/** A reading for the hover and point readout. Log layers store values below their floor
 * (including zero) as the floor, so all that is known there is "less than the floor". */
export function formatReading(v: number, units: string, enc: EncodeRange): string {
  if (enc.log && Number.isFinite(v) && v <= enc.lo * (1 + 1e-9)) return `< ${enc.lo} ${prettyUnits(units)}`;
  return formatValue(v, units, enc);
}
