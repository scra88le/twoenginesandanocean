// The zonal budget panel (docs/PROPOSALS-v2.md F7): Engine 2 after Kleidon (2023). Two charts
// that share an x-axis linear in sin φ, so the area under a curve is honest: zonal absorbed and
// radiated heat on top, northward transport below. All numbers come from the pipeline's JSON.
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import {
  LAT_TICKS, latLabel, panelData, shadeBands, sinLat, summaryLines, twoBoxText, type Zonal,
} from './zonal';
import type { Frame } from './modes';

const AXIS = { stroke: '#a3a9b4', grid: { stroke: 'rgba(255,255,255,0.06)' }, ticks: { stroke: 'rgba(255,255,255,0.1)' } };
const COLORS = { asr: '#ff7a59', olr: '#5aa0ff', total: '#e6e8ec', atm: '#c3a2ff', ocean: '#4ec9b0' };
const FILL = { surplus: 'rgba(255, 122, 89, 0.28)', deficit: 'rgba(90, 160, 255, 0.28)' };

const xAxis = (): uPlot.Axis => ({
  ...AXIS,
  size: 28,
  splits: () => LAT_TICKS.map(sinLat),
  values: (_u, v) => v.map((s) => latLabel(Math.round((Math.asin(s) * 180) / Math.PI))),
});

export class ZonalPanel {
  private readonly heading: HTMLElement;
  private readonly note: HTMLElement;
  private readonly topBox: HTMLElement;
  private readonly bottomBox: HTMLElement;
  private readonly legend: HTMLElement;
  private readonly twoBox: HTMLElement;
  private readonly summary: HTMLElement;
  private charts: uPlot[] = [];

  constructor(
    private readonly root: HTMLElement,
    onClose: () => void,
  ) {
    root.innerHTML = `
      <div class="zb-head">
        <div><h2 class="zb-heading">Zonal budget</h2><div class="zb-place"></div></div>
        <button type="button" class="zb-close" aria-label="Close the zonal budget">×</button>
      </div>
      <div class="zb-title">Sunlight absorbed and heat radiated (W m⁻²) by latitude</div>
      <div class="zb-chart zb-top"></div>
      <div class="zb-title">Northward heat transport (PW)</div>
      <div class="zb-chart zb-bottom"></div>
      <ul class="zb-legend"></ul>
      <p class="zb-twobox"></p>
      <details class="zb-details"><summary>The numbers as text</summary><ul class="zb-summary"></ul></details>
      <p class="zb-note"></p>`;
    this.heading = root.querySelector('.zb-place')!;
    this.topBox = root.querySelector('.zb-top')!;
    this.bottomBox = root.querySelector('.zb-bottom')!;
    this.legend = root.querySelector('.zb-legend')!;
    this.twoBox = root.querySelector('.zb-twobox')!;
    this.summary = root.querySelector('.zb-summary')!;
    this.note = root.querySelector('.zb-note')!;
    root.querySelector('.zb-close')!.addEventListener('click', onClose);
    root.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') onClose();
    });
  }

  get isOpen(): boolean {
    return !this.root.hidden;
  }

  open(): void {
    this.root.hidden = false;
  }

  close(): void {
    this.root.hidden = true;
    this.clear();
  }

  private clear(): void {
    for (const c of this.charts) c.destroy();
    this.charts = [];
    this.topBox.innerHTML = '';
    this.bottomBox.innerHTML = '';
  }

  /** Draw a frame or date, or say why there is nothing to draw (`z` null). `what` names it, e.g. "July" or "2026-10-01". */
  show(z: Zonal | null, frame: Frame | null, what: string, detail: string): void {
    this.heading.textContent = what;
    this.clear();
    if (!z) {
      this.legend.innerHTML = '';
      this.twoBox.textContent = '';
      this.summary.innerHTML = '';
      this.note.textContent = `No zonal budget is published for ${what} yet.`;
      return;
    }
    this.note.textContent = detail;
    const d = panelData(z);
    const width = Math.max(240, this.topBox.clientWidth || 440);
    const bands = shadeBands(d.x, d.asr, d.olr);

    const top: uPlot.Options = {
      width, height: 190, legend: { show: false }, cursor: { drag: { x: false, y: false } },
      scales: { x: { time: false, range: [-1, 1] }, y: { auto: true } },
      axes: [xAxis(), { ...AXIS, size: 44 }],
      series: [
        {},
        { stroke: COLORS.asr, width: 2, points: { show: false } },
        { stroke: COLORS.olr, width: 2, points: { show: false } },
      ],
      hooks: {
        // surplus and deficit, drawn under the lines
        drawClear: [
          (u) => {
            const ctx = u.ctx;
            for (const b of bands) {
              ctx.beginPath();
              b.x.forEach((x, i) => ctx[i ? 'lineTo' : 'moveTo'](u.valToPos(x, 'x', true), u.valToPos(b.hi[i] as number, 'y', true)));
              for (let i = b.x.length - 1; i >= 0; i--) ctx.lineTo(u.valToPos(b.x[i] as number, 'x', true), u.valToPos(b.lo[i] as number, 'y', true));
              ctx.closePath();
              ctx.fillStyle = b.sign > 0 ? FILL.surplus : FILL.deficit;
              ctx.fill();
            }
          },
        ],
      },
    };
    const bottom: uPlot.Options = {
      width, height: 170, legend: { show: false }, cursor: { drag: { x: false, y: false } },
      scales: { x: { time: false, range: [-1, 1] }, y: { auto: true } },
      axes: [xAxis(), { ...AXIS, size: 44 }],
      series: [
        {},
        { stroke: COLORS.total, width: 2, points: { show: false } },
        { stroke: COLORS.atm, width: 2, points: { show: false } },
        ...(d.ocean ? [{ stroke: COLORS.ocean, width: 2, dash: [5, 4], points: { show: false } }] : []),
      ],
    };
    this.charts = [
      new uPlot(top, [d.x, d.asr, d.olr], this.topBox),
      new uPlot(bottom, [d.ex, d.total, d.atm, ...(d.ocean ? [d.ocean] : [])], this.bottomBox),
    ];
    this.topBox.setAttribute('role', 'img');
    this.topBox.setAttribute('aria-label', `Zonal absorbed sunlight and radiated heat for ${what}. ${summaryLines(z)[0] ?? ''}`);
    this.bottomBox.setAttribute('role', 'img');
    this.bottomBox.setAttribute('aria-label', `Northward heat transport for ${what}.`);

    const key: [string, string][] = [
      [COLORS.asr, 'Sunlight absorbed'], [COLORS.olr, 'Heat radiated to space'],
      [COLORS.total, 'Total transport (from the top-of-atmosphere budget)'], [COLORS.atm, 'Atmosphere'],
      ...(d.ocean ? [[COLORS.ocean, 'Ocean (total minus atmosphere)'] as [string, string]] : []),
    ];
    this.legend.replaceChildren(
      ...key.map(([c, t]) => {
        const li = document.createElement('li');
        const sw = document.createElement('span');
        sw.className = 'zb-swatch';
        sw.style.background = c;
        li.append(sw, t);
        return li;
      }),
    );
    this.twoBox.textContent = twoBoxText(z, frame);
    this.summary.replaceChildren(
      ...summaryLines(z).map((t) => {
        const li = document.createElement('li');
        li.textContent = t;
        return li;
      }),
    );
  }
}
