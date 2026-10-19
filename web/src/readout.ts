// Point readout ("local engine"): every stage of the heat engine at one cell, and a 90-day
// chart of the active layer there. Values come from point and series chunks.
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { FIRST_VALID, MASKED, NODATA, decodeValue, type EncodeRange } from './codes';
import { formatReading, prettyUnits } from './format';
import type { LayerMeta, Manifest } from './manifest';

/** The table rows from the spec, with short names for each quantity. */
export const READOUT_ROWS: { label: string; items: [string, string][] }[] = [
  { label: 'Fuel', items: [['asr_sfc', 'Absorbed solar, surface']] },
  { label: 'Hot side', items: [['t_skin', 'T_s']] },
  { label: 'Cold side', items: [['t_emit', 'T_e']] },
  { label: 'Ceiling', items: [['carnot', 'η_C']] },
  { label: 'Max power', items: [['j_opt', 'J_opt'], ['g_max', 'G_max']] },
  { label: 'Actual', items: [['j_conv', 'LE + H'], ['j_ratio', 'r_J']] },
  { label: 'Split', items: [['lh', 'LE'], ['sh', 'H'], ['evap_frac', 'EF']] },
  { label: 'Output', items: [['diss_bl', 'BL dissipation'], ['wind100', 'Wind 100 m']] },
  { label: 'Water', items: [['precip', 'Precipitation'], ['p_lift', 'P_lift']] },
  { label: 'Humans', items: [['human_q', 'q_human'], ['human_ratio', 'r_H']] },
];

export interface ReadoutItem {
  id: string;
  name: string;
  text: string;
  note?: string; // why a value isn't shown
}

interface FieldInfo {
  units: string;
  encode: EncodeRange;
  mask: string | null;
}

function fieldInfo(m: Manifest, id: string): FieldInfo | null {
  const layer = m.layers[id];
  if (layer) return { units: layer.units, encode: layer.encode, mask: layer.info.mask };
  const extra = m.points?.extras[id];
  // J_opt is land-only, like G_max: it comes from the same model.
  return extra ? { units: extra.units, encode: extra.encode, mask: id === 'j_opt' ? (m.layers.g_max?.info.mask ?? null) : null } : null;
}

/** Text for every quantity in the table, from the codes at one cell. */
export function readoutItems(m: Manifest, codes: Map<string, number>): { label: string; items: ReadoutItem[] }[] {
  return READOUT_ROWS.map(({ label, items }) => ({
    label,
    items: items.map(([id, name]) => {
      const info = fieldInfo(m, id);
      const code = codes.get(id);
      const built = !m.layers[id] || m.built_layers.includes(id);
      if (!info || code === undefined || !built) return { id, name, text: 'not available yet' };
      if (code === MASKED) return { id, name, text: '—', note: info.mask ?? 'Not shown here' };
      if (code === NODATA) return { id, name, text: 'no data' };
      return { id, name, text: formatReading(decodeValue(code, info.encode), info.units, info.encode) };
    }),
  }));
}

const DAY_S = 86400;
const noon = (d: string) => Date.parse(`${d}T12:00:00Z`) / 1000;

/**
 * Chart data: one x per day from the first date to the last (unix seconds, noon UTC) and the
 * value on it, null where a date has no value or isn't published, so gaps show as gaps.
 */
export function seriesData(dates: string[], codes: Uint16Array, enc: EncodeRange): [number[], (number | null)[]] {
  if (!dates.length) return [[], []];
  const first = noon(dates[0]!);
  const days = Math.round((noon(dates.at(-1)!) - first) / DAY_S) + 1;
  const xs = Array.from({ length: days }, (_, k) => first + k * DAY_S);
  const ys: (number | null)[] = new Array<number | null>(days).fill(null);
  dates.forEach((d, n) => {
    const c = codes[n]!;
    if (c >= FIRST_VALID) ys[Math.round((noon(d) - first) / DAY_S)] = decodeValue(c, enc);
  });
  return [xs, ys];
}

/** "39.75° N, 0.25° E" for a cell centre. */
export function formatPlace(lng: number, lat: number): string {
  const f = (v: number, pos: string, neg: string) => `${Math.abs(v).toFixed(2)}° ${v >= 0 ? pos : neg}`;
  return `${f(lat, 'N', 'S')}, ${f(lng, 'E', 'W')}`;
}

export class ReadoutPanel {
  private readonly title: HTMLElement;
  private readonly table: HTMLTableElement;
  private readonly chartTitle: HTMLElement;
  private readonly chartBox: HTMLElement;
  private readonly chartNote: HTMLElement;
  private chart: uPlot | null = null;

  constructor(
    private readonly root: HTMLElement,
    onClose: () => void,
  ) {
    root.innerHTML = `
      <div class="ro-head">
        <div><h2 class="ro-heading">Local engine</h2><div class="ro-place"></div></div>
        <button type="button" class="ro-close" aria-label="Close the readout">×</button>
      </div>
      <table class="ro-table"></table>
      <div class="ro-chart-title"></div>
      <div class="ro-chart"></div>
      <div class="ro-chart-note"></div>`;
    this.title = root.querySelector('.ro-place')!;
    this.table = root.querySelector<HTMLTableElement>('.ro-table')!;
    this.chartTitle = root.querySelector('.ro-chart-title')!;
    this.chartBox = root.querySelector('.ro-chart')!;
    this.chartNote = root.querySelector('.ro-chart-note')!;
    root.querySelector('.ro-close')!.addEventListener('click', onClose);
    root.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') onClose();
    });
  }

  open(): void {
    this.root.hidden = false;
  }

  close(): void {
    this.root.hidden = true;
    this.chart?.destroy();
    this.chart = null;
  }

  get isOpen(): boolean {
    return !this.root.hidden;
  }

  showPlace(lng: number, lat: number, date: string): void {
    this.title.textContent = `${formatPlace(lng, lat)} · ${date}`;
  }

  showTable(rows: { label: string; items: ReadoutItem[] }[] | string): void {
    this.table.innerHTML = '';
    if (typeof rows === 'string') {
      const tr = this.table.insertRow();
      const td = tr.insertCell();
      td.colSpan = 2;
      td.className = 'ro-message';
      td.textContent = rows;
      return;
    }
    for (const row of rows) {
      const tr = this.table.insertRow();
      const th = document.createElement('th');
      th.scope = 'row';
      th.textContent = row.label;
      tr.append(th);
      const td = tr.insertCell();
      for (const item of row.items) {
        const div = document.createElement('div');
        div.className = 'ro-item';
        div.dataset.id = item.id;
        const name = document.createElement('span');
        name.className = 'ro-name';
        name.textContent = `${item.name} `;
        const value = document.createElement('span');
        value.className = 'ro-value';
        value.textContent = item.text;
        if (item.note) {
          value.title = item.note;
          value.setAttribute('aria-label', `not shown: ${item.note}`);
        }
        div.append(name, value);
        td.append(div);
      }
    }
  }

  /** The 90-day chart of the active layer at this point, marking the date on the map. */
  showChart(meta: LayerMeta, dates: string[], codes: Uint16Array, current: string): void {
    const [xs, ys] = seriesData(dates, codes, meta.encode);
    this.chartTitle.textContent = `${meta.title} (${prettyUnits(meta.units)}), ${dates[0]} to ${dates.at(-1)}`;
    const valid = ys.filter((y): y is number => y !== null);
    this.chartNote.textContent = valid.length
      ? 'Climatology line: not available yet.'
      : 'No values here on these dates (masked or no data).';
    const i = xs.indexOf(noon(current));
    const marker: (number | null)[] = ys.map((y, k) => (k === i ? y : null));
    const width = Math.max(200, this.chartBox.clientWidth || 300);
    const opts: uPlot.Options = {
      width,
      height: 150,
      legend: { show: false },
      cursor: { drag: { x: false, y: false } },
      scales: { x: { time: true }, y: meta.log ? { distr: 3, log: 10 } : { auto: true } },
      axes: [
        { stroke: '#a3a9b4', grid: { stroke: 'rgba(255,255,255,0.06)' }, ticks: { stroke: 'rgba(255,255,255,0.1)' }, size: 30 },
        { stroke: '#a3a9b4', grid: { stroke: 'rgba(255,255,255,0.06)' }, ticks: { stroke: 'rgba(255,255,255,0.1)' }, size: 52 },
      ],
      series: [
        {},
        // Dots as well as the line, so a day with no neighbours still shows.
        { stroke: '#7aa7ff', width: 1.5, spanGaps: false, points: { show: true, size: 3, fill: '#7aa7ff' } },
        { stroke: '#ffffff', fill: '#ffffff', width: 0, points: { show: true, size: 7, fill: '#ffffff' } },
      ],
    };
    this.chart?.destroy();
    this.chartBox.innerHTML = '';
    this.chart = new uPlot(opts, [xs, ys, marker], this.chartBox);
    this.chartBox.setAttribute('role', 'img');
    this.chartBox.setAttribute('aria-label', `${meta.title} at this point: ${valid.length} of ${dates.length} days have values`);
  }

  showChartMessage(text: string): void {
    this.chart?.destroy();
    this.chart = null;
    this.chartBox.innerHTML = '';
    this.chartTitle.textContent = '';
    this.chartNote.textContent = text;
  }
}
