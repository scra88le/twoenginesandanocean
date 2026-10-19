// Point and series chunks: 10 x 10 degree tiles of uint16 codes, written by
// pipeline/src/pipeline/points.py. All values are little-endian.

/** Which tile a grid cell is in, and its index within the tile (row-major). */
export function tileOf(cell: { i: number; j: number }, tile: number): { tx: number; ty: number; k: number } {
  return {
    tx: Math.floor(cell.i / tile),
    ty: Math.floor(cell.j / tile),
    k: (cell.j % tile) * tile + (cell.i % tile),
  };
}

/** Codes of every field at one cell of a point chunk (field-major, tile x tile per field). */
export function pointCodes(buf: ArrayBuffer, fields: string[], tile: number, k: number): Map<string, number> {
  const n = tile * tile;
  if (buf.byteLength !== fields.length * n * 2) throw new Error(`point chunk is ${buf.byteLength} bytes, expected ${fields.length * n * 2}`);
  const view = new DataView(buf);
  return new Map(fields.map((f, idx) => [f, view.getUint16((idx * n + k) * 2, true)]));
}

export interface Series {
  dates: string[];
  view: DataView;
  offset: number; // byte offset of the codes
}

const MAGIC = 'EHS1';

/** Parse a series chunk: "EHS1", uint32 n, n uint32 dates as YYYYMMDD, then n tiles of codes. */
export function parseSeries(buf: ArrayBuffer, tile: number): Series {
  const view = new DataView(buf);
  const magic = String.fromCharCode(...new Uint8Array(buf, 0, 4));
  if (magic !== MAGIC) throw new Error('not a series chunk');
  const n = view.getUint32(4, true);
  const offset = 8 + 4 * n;
  if (buf.byteLength !== offset + n * tile * tile * 2) throw new Error('series chunk has the wrong length');
  const dates = Array.from({ length: n }, (_, d) => {
    const s = view.getUint32(8 + 4 * d, true);
    return `${Math.floor(s / 10000)}-${String(Math.floor(s / 100) % 100).padStart(2, '0')}-${String(s % 100).padStart(2, '0')}`;
  });
  return { dates, view, offset };
}

/** The codes at one cell, one per date. */
export function seriesCodes(s: Series, tile: number, k: number): Uint16Array {
  const out = new Uint16Array(s.dates.length);
  for (let d = 0; d < out.length; d++) out[d] = s.view.getUint16(s.offset + (d * tile * tile + k) * 2, true);
  return out;
}
