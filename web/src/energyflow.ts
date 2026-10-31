// The readout's energy-flow diagram (docs/PROPOSALS-v2.md F11 §4): the surface column at the
// clicked cell. Sunlight absorbed goes in; latent heat, sensible heat and infrared leave; what is
// left is the net heat into (or out of) the surface. Arrow widths share one scale, so a wider
// arrow is a bigger flow; every value is also written as text.
import { MASKED, NODATA, decodeValue } from './codes';
import { prettyUnits } from './format';
import type { Manifest } from './manifest';

export interface Flow {
  sun: number; // sunlight absorbed at the surface, W m⁻²
  le: number; // latent heat flux, up
  h: number; // sensible heat flux, up
  ir: number; // net infrared lost, up
  net: number; // net heat into the surface (+) or out of it (−)
}

/**
 * The five flows at a cell from its point codes, or null when a layer is not built or has no value
 * here. `lw_up` is not a map layer or a point field; it is the one term of the published surface
 * budget net_sfc = asr_sfc − lw_up − lh − sh that is left over, so it is read from the other four
 * rather than recomputed from ERA5 (docs/DECISIONS.md, milestone 21).
 */
export function flowValues(m: Manifest, codes: Map<string, number>): Flow | null {
  const get = (id: string): number | null => {
    const layer = m.layers[id];
    const code = codes.get(id);
    if (!layer || !m.built_layers.includes(id) || code === undefined || code === MASKED || code === NODATA) return null;
    const v = decodeValue(code, layer.encode);
    return Number.isFinite(v) ? v : null;
  };
  const [sun, le, h, net] = ['asr_sfc', 'lh', 'sh', 'net_sfc'].map(get);
  if (sun == null || le == null || h == null || net == null) return null;
  return { sun, le, h, ir: sun - le - h - net, net };
}

/** Arrow widths in px on one scale: the largest flow gets `maxPx`, none is thinner than `minPx`. */
export function flowWidths(f: Flow, maxPx = 26, minPx = 1.5): Flow {
  const top = Math.max(...Object.values(f).map(Math.abs), 1e-9);
  const w = (v: number) => Math.max(minPx, (Math.abs(v) / top) * maxPx);
  return { sun: w(f.sun), le: w(f.le), h: w(f.h), ir: w(f.ir), net: w(f.net) };
}

const wm2 = (v: number) => `${Math.round(v).toString().replace('-', '−')} ${prettyUnits('W m-2')}`;

/** The same content as text, for the accessible name and the tests. */
export function flowText(f: Flow): string {
  const dir = f.net >= 0 ? 'into' : 'out of';
  return (
    `At the surface: sunlight absorbed ${wm2(f.sun)}. Heat leaving: latent ${wm2(f.le)}, ` +
    `sensible ${wm2(f.h)}, infrared ${wm2(f.ir)}. Net heat ${dir} the surface: ${wm2(Math.abs(f.net))}.`
  );
}

const NS = 'http://www.w3.org/2000/svg';
const el = (name: string, attrs: Record<string, string | number>, text?: string) => {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
};

/** An arrow along a vertical line from y1 to y2, `w` wide, with a head at y2. */
function arrow(x: number, y1: number, y2: number, w: number, colour: string): SVGElement[] {
  const dir = Math.sign(y2 - y1) || 1;
  const head = 10;
  const hw = Math.max(w / 2 + 4, 7);
  const base = y2 - dir * head;
  return [
    el('line', { x1: x, y1, x2: x, y2: base, stroke: colour, 'stroke-width': w }),
    el('polygon', { points: `${x - hw},${base} ${x + hw},${base} ${x},${y2}`, fill: colour }),
  ];
}

/** Draw the diagram into `root`; null hides it (a layer it needs is not built, or the cell has no value). */
export function renderFlow(root: HTMLElement, f: Flow | null): void {
  root.replaceChildren();
  root.hidden = f === null;
  if (!f) return;
  const w = flowWidths(f);
  const text = flowText(f);
  const svg = el('svg', { viewBox: '0 0 320 150', role: 'img', 'aria-label': text, class: 'ef-svg' });
  svg.append(el('title', {}, 'Energy flows at the surface'));
  const cols: [number, string, string, number, string][] = [
    // x, name, colour, signed value, width key
    [32, 'Sunlight', '#f4c542', f.sun, 'sun'],
    [96, 'Latent', '#3cc3b4', f.le, 'le'],
    [160, 'Sensible', '#f08a3c', f.h, 'h'],
    [224, 'Infrared', '#ee6a50', f.ir, 'ir'],
    [288, f.net >= 0 ? 'Net in' : 'Net out', '#8fc0ff', Math.abs(f.net), 'net'],
  ];
  const g = el('g', { 'aria-hidden': 'true' });
  g.append(el('line', { x1: 8, y1: 78, x2: 312, y2: 78, stroke: '#6b7384', 'stroke-width': 2 }));
  for (const [x, name, colour, value, key] of cols) {
    const width = w[key as keyof Flow];
    // the sun and the net flow (when positive) point down into the surface; the heat flows point up
    const down = key === 'sun' || (key === 'net' && f.net >= 0);
    const up = key === 'net' ? !down : value >= 0 && !down;
    const [y1, y2] = key === 'net' ? (down ? [60, 100] : [100, 60]) : down ? [8, 74] : up ? [74, 12] : [12, 74];
    g.append(...arrow(x, y1, y2, width, colour));
    g.append(el('text', { x, y: 122, 'text-anchor': 'middle', class: 'ef-name' }, name));
    g.append(el('text', { x, y: 138, 'text-anchor': 'middle', class: 'ef-value' }, wm2(value)));
  }
  svg.append(g);
  root.append(svg);
}
