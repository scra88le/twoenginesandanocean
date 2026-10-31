// The AMOC trend panel: the overturning strength across the 26.5° N section for every date with
// ocean data, daily and as the 30-day mean. All numbers come from the manifest's `ocean.dates`.
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { amocTrend, amocTrendText, type OceanMeta } from './ocean';

const AXIS = { stroke: '#a3a9b4', grid: { stroke: 'rgba(255,255,255,0.06)' }, ticks: { stroke: 'rgba(255,255,255,0.1)' } };
const COLORS = { daily: 'rgba(240, 138, 93, 0.55)', mean: '#6fb6f2' };

export class AmocPanel {
  private readonly box: HTMLElement;
  private readonly summary: HTMLElement;
  private readonly note: HTMLElement;
  private chart: uPlot | null = null;

  constructor(
    private readonly root: HTMLElement,
    private readonly ocean: OceanMeta | null,
    onClose: () => void,
  ) {
    root.innerHTML = `
      <div class="zb-head">
        <div><h2 class="zb-heading">AMOC trend</h2><div class="zb-place"></div></div>
        <button type="button" class="zb-close" aria-label="Close the AMOC trend">×</button>
      </div>
      <div class="zb-title">Overturning strength across the section (Sv)</div>
      <div class="zb-chart amoc-chart"></div>
      <ul class="zb-legend">
        <li><span class="zb-swatch" style="background:${COLORS.daily}"></span>Daily</li>
        <li><span class="zb-swatch" style="background:${COLORS.mean}"></span>30-day mean</li>
      </ul>
      <details class="zb-details"><summary>The numbers as text</summary><ul class="zb-summary"></ul></details>
      <p class="zb-note"></p>`;
    this.box = root.querySelector('.amoc-chart')!;
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
    this.draw();
  }

  close(): void {
    this.root.hidden = true;
    this.chart?.destroy();
    this.chart = null;
  }

  private draw(): void {
    this.chart?.destroy();
    this.chart = null;
    this.box.innerHTML = '';
    const o = this.ocean;
    const tr = o ? amocTrend(o) : null;
    const place = this.root.querySelector('.zb-place')!;
    if (!o || !tr || !tr.dates.length) {
      place.textContent = '';
      this.summary.innerHTML = '';
      this.note.textContent = 'No ocean currents have been published yet.';
      return;
    }
    place.textContent = `${o.section.lat}° N, ${o.section.lon[0]}° to ${o.section.lon[1]}°`;
    const opts: uPlot.Options = {
      width: Math.max(240, this.box.clientWidth || 440),
      height: 200,
      legend: { show: false },
      cursor: { drag: { x: false, y: false } },
      scales: { y: { range: (_u, lo, hi) => [Math.min(0, lo), Math.max(hi * 1.1, 1)] } },
      axes: [AXIS, { ...AXIS, size: 44 }],
      series: [
        {},
        { stroke: COLORS.daily, width: 1, points: { show: false } },
        { stroke: COLORS.mean, width: 2.5, points: { show: false }, spanGaps: false },
      ],
    };
    this.chart = new uPlot(opts, [tr.t, tr.daily, tr.mean], this.box);
    const lines = amocTrendText(tr);
    this.box.setAttribute('role', 'img');
    this.box.setAttribute('aria-label', `AMOC strength over time. ${lines.slice(0, 3).join(' ')}`);
    this.summary.replaceChildren(
      ...lines.map((t) => {
        const li = document.createElement('li');
        li.textContent = t;
        return li;
      }),
    );
    this.note.textContent = `${o.dataset}, daily-mean currents; ψ is the zonal integral of the northward flow from the surface down, its maximum over depth.`;
  }
}
