// Colour tables exported from matplotlib / cmocean by pipeline/scripts/export_colormaps.py.
import tables from './colormap-tables.json' with { type: 'json' };

const TABLES = tables as Record<string, string>;
export const MAP_NAMES = Object.keys(TABLES);

function table(name: string): string {
  const t = TABLES[name];
  if (!t) throw new Error(`unknown colour scale ${name}`);
  return t;
}

export function colourAt(name: string, t: number): [number, number, number] {
  const k = Math.round(Math.min(1, Math.max(0, t)) * 255) * 6;
  const hex = table(name);
  return [0, 2, 4].map((o) => parseInt(hex.slice(k + o, k + o + 2), 16)) as [number, number, number];
}

/** 256 x 1 RGBA texture data. */
export function lutBytes(name: string): Uint8Array {
  const hex = table(name);
  const out = new Uint8Array(256 * 4);
  for (let k = 0; k < 256; k++) {
    for (let c = 0; c < 3; c++) out[4 * k + c] = parseInt(hex.slice(6 * k + 2 * c, 6 * k + 2 * c + 2), 16);
    out[4 * k + 3] = 255;
  }
  return out;
}

export function cssGradient(name: string, stops = 16): string {
  const parts = Array.from({ length: stops }, (_, k) => {
    const t = k / (stops - 1);
    const [r, g, b] = colourAt(name, t);
    return `rgb(${r}, ${g}, ${b}) ${Math.round(t * 100)}%`;
  });
  return `linear-gradient(to right, ${parts.join(', ')})`;
}
