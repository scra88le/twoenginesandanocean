// Reserved codes and value decoding. Mirrors pipeline/src/pipeline/encode.py.
import type { DecodedPng } from './png';

export const NODATA = 0;
export const MASKED = 1;
export const FIRST_VALID = 2;

export interface EncodeRange {
  lo: number;
  hi: number;
  log: boolean;
  scale: number;
  offset: number;
}

export function scalarCodes(png: DecodedPng): Uint16Array {
  if (png.channels !== 3) throw new Error('scalar layers are RGB PNGs');
  const n = png.width * png.height;
  const out = new Uint16Array(n);
  for (let k = 0; k < n; k++) out[k] = (png.data[3 * k]! << 8) | png.data[3 * k + 1]!;
  return out;
}

export function vectorCodes(png: DecodedPng): { u: Uint16Array; v: Uint16Array } {
  if (png.channels !== 4) throw new Error('vector layers are RGBA PNGs');
  const n = png.width * png.height;
  const u = new Uint16Array(n);
  const v = new Uint16Array(n);
  for (let k = 0; k < n; k++) {
    u[k] = (png.data[4 * k]! << 8) | png.data[4 * k + 1]!;
    v[k] = (png.data[4 * k + 2]! << 8) | png.data[4 * k + 3]!;
  }
  return { u, v };
}

/** Code -> value in layer units; NaN for no data and masked. */
export function decodeValue(code: number, enc: EncodeRange): number {
  if (code < FIRST_VALID) return NaN;
  const x = enc.offset + enc.scale * (code - FIRST_VALID);
  return enc.log ? 10 ** x : x;
}

export function decodeAll(codes: Uint16Array, enc: EncodeRange): Float64Array {
  const out = new Float64Array(codes.length);
  for (let k = 0; k < codes.length; k++) out[k] = decodeValue(codes[k]!, enc);
  return out;
}
