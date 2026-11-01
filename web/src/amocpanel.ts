// The AMOC panel. Top: the Atlantic's overturning streamfunction on a latitude-depth section for
// the map's date (`ocean/{date}/section*.json`), with its strength at each latitude below it.
// Bottom: the strength across the 26.5° N section for every date with ocean data, daily and as
// the 30-day mean (the manifest's `ocean.dates`). The pipeline computes every number.
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import {
  amocTrend,
  beltBins,
  beltText,
  amocTrendText,
  parseSection,
  psiColour,
  sectionAvg,
  sectionStrength,
  sectionText,
  sectionUrl,
  type BeltBin,
  type OceanAvg,
  type OceanMeta,
  type SectionField,
} from './ocean';

const AXIS = { stroke: '#a3a9b4', grid: { stroke: 'rgba(255,255,255,0.06)' }, ticks: { stroke: 'rgba(255,255,255,0.1)' } };
const COLORS = { daily: 'rgba(240, 138, 93, 0.55)', mean: '#6fb6f2' };
const VMAX = 25; // Sv drawn in full colour; fixed so dates compare
const MARGIN = { l: 44, r: 8, t: 6, b: 22 };
const HEAT_H = 230;
const DEPTH_TICKS = [0, 250, 1000, 2000, 3000, 4000, 5000];
const LAT_TICKS = [-40, -20, 0, 20, 40, 60, 80];
const BELT_H = 150;
const sqrtDepth = (z: number) => Math.sqrt(Math.max(0, z));

export class AmocPanel {
  private readonly box: HTMLElement;
  private readonly summary: HTMLElement;
  private readonly note: HTMLElement;
  private chart: uPlot | null = null;
  private strengthChart: uPlot | null = null;
  private readonly belt: HTMLCanvasElement;
  private readonly heat: HTMLCanvasElement;
  private readonly heatNote: HTMLElement;
  private readonly heatText: HTMLElement;
  private readonly strengthBox: HTMLElement;
  private readonly cache = new Map<string, Promise<SectionField>>();
  private view: { date: string; climate: boolean } | null = null;
  private requested = 0;

  constructor(
    private readonly root: HTMLElement,
    private readonly ocean: OceanMeta | null,
    private readonly base: string,
    onClose: () => void,
  ) {
    root.innerHTML = `
      <div class="zb-head">
        <div><h2 class="zb-heading">Atlantic overturning</h2><div class="zb-place"></div></div>
        <button type="button" class="zb-close" aria-label="Close the AMOC panel">×</button>
      </div>
      <div class="zb-title">The two limbs, summed across the whole Atlantic (Sv)</div>
      <canvas class="amoc-belt" role="img"></canvas>
      <ul class="zb-legend amoc-belt-key">
        <li><span class="zb-swatch" style="background:#f08a5d"></span>Upper limb, 0–1,100 m</li>
        <li><span class="zb-swatch" style="background:#6fb6f2"></span>Deep limb, below 1,100 m</li>
        <li>Arrows: the direction of flow; thickness: how much</li>
      </ul>
      <div class="zb-title amoc-section-title">Overturning streamfunction, latitude and depth (Sv)</div>
      <canvas class="amoc-heat" role="img"></canvas>
      <ul class="zb-legend amoc-key">
        <li><span class="zb-swatch" style="background:#f08a5d"></span>Clockwise: northward above, southward below</li>
        <li><span class="zb-swatch" style="background:#6fb6f2"></span>Counter-clockwise</li>
      </ul>
      <div class="zb-title">Strength at each latitude (Sv)</div>
      <div class="zb-chart amoc-strength"></div>
      <details class="zb-details"><summary>The section as text</summary><ul class="amoc-heat-text zb-summary"></ul></details>
      <p class="zb-note amoc-heat-note"></p>
      <div class="zb-title">Strength across 26.5° N over time (Sv)</div>
      <div class="zb-chart amoc-chart"></div>
      <ul class="zb-legend">
        <li><span class="zb-swatch" style="background:${COLORS.daily}"></span>Daily</li>
        <li><span class="zb-swatch" style="background:${COLORS.mean}"></span>30-day mean</li>
      </ul>
      <details class="zb-details"><summary>The numbers as text</summary><ul class="zb-summary amoc-trend-text"></ul></details>
      <p class="zb-note"></p>`;
    this.belt = root.querySelector('.amoc-belt')!;
    this.heat = root.querySelector('.amoc-heat')!;
    this.heatNote = root.querySelector('.amoc-heat-note')!;
    this.heatText = root.querySelector('.amoc-heat-text')!;
    this.strengthBox = root.querySelector('.amoc-strength')!;
    this.box = root.querySelector('.amoc-chart')!;
    this.summary = root.querySelector('.amoc-trend-text')!;
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
    void this.drawSection();
  }

  close(): void {
    this.root.hidden = true;
    this.chart?.destroy();
    this.chart = null;
    this.strengthChart?.destroy();
    this.strengthChart = null;
  }

  /** The map's date changed (or its mode): show that date's section. Climate has no normal for
   * the ocean, so it shows the newest 30-day mean, as the overlay does. */
  setView(date: string, climate: boolean): void {
    this.view = { date, climate };
    if (this.isOpen) void this.drawSection();
  }

  private pick(): { date: string; avg: OceanAvg; note: string } | null {
    const o = this.ocean;
    if (!o?.section_grid) return null;
    if (this.view?.climate) {
      const date = Object.keys(o.dates).filter((d) => o.dates[d]!.section?.mean).sort().pop();
      return date ? { date, avg: 'mean', note: ' There is no 1991–2020 normal for the ocean, so this is the newest 30-day mean.' } : null;
    }
    const date = this.view?.date ?? Object.keys(o.dates).sort().pop();
    if (!date) return null;
    const avg = sectionAvg(o, date, 'mean');
    return avg ? { date, avg, note: avg === 'mean' ? '' : ' The 30-day mean is not available for this date, so this is the daily mean.' } : null;
  }

  private async drawSection(): Promise<void> {
    const request = ++this.requested;
    const o = this.ocean;
    const pick = this.pick();
    const clear = (msg: string) => {
      this.strengthChart?.destroy();
      this.strengthChart = null;
      this.heat.getContext('2d')?.clearRect(0, 0, this.heat.width, this.heat.height);
      this.belt.getContext('2d')?.clearRect(0, 0, this.belt.width, this.belt.height);
      this.heat.setAttribute('aria-label', msg);
      this.heatText.replaceChildren();
      this.heatNote.textContent = msg;
    };
    if (!o || !pick) return clear(o?.section_grid ? 'No latitude–depth section for this date yet.' : 'The latitude–depth section has not been published yet.');
    const url = sectionUrl(this.base, o, pick.date, pick.avg);
    let p = this.cache.get(url);
    if (!p) {
      p = fetch(url).then(async (r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return parseSection(await r.json(), o.section_grid!);
      });
      this.cache.set(url, p);
      p.catch(() => this.cache.delete(url));
    }
    let sec: SectionField;
    try {
      sec = await p;
    } catch {
      if (request === this.requested) clear(`The section for ${pick.date} could not be loaded.`);
      return;
    }
    if (request !== this.requested || !this.isOpen) return;
    const what = pick.avg === 'mean' ? `${o.window_days}-day mean to ${pick.date}` : `daily mean, ${pick.date}`;
    this.paintBelt(sec);
    this.paintHeat(sec);
    this.drawStrength(sec);
    const belt = beltText(sec, o);
    this.belt.setAttribute('aria-label', `Net transport of the upper and deep limbs by latitude, ${what}. ${belt.join(' ') || 'Not available for this date.'}`);
    const heat = sectionText(sec, o);
    const lines = [...belt, ...heat];
    this.heat.setAttribute('aria-label', `Atlantic overturning streamfunction by latitude and depth, ${what}. ${heat[0]}`);
    this.heatText.replaceChildren(...lines.map((t) => Object.assign(document.createElement('li'), { textContent: t })));
    this.heatNote.textContent =
      `${what}. Each limb is its water's net transport across the latitude circle, so eddies and gyres cancel. ψ is the northward volume transport of the whole Atlantic above each depth; colour is to ±${VMAX} Sv, and the line marks ${o.section.lat}° N.` +
      pick.note;
  }

  /** The conveyor belt: one lane per limb along the latitude axis, a ribbon as thick as the
   * transport with arrowheads for the direction (north is right). */
  private paintBelt(sec: SectionField): void {
    const w = Math.max(240, this.strengthBox.clientWidth || 440);
    const dpr = window.devicePixelRatio || 1;
    this.belt.style.width = `${w}px`;
    this.belt.style.height = `${BELT_H}px`;
    this.belt.width = Math.round(w * dpr);
    this.belt.height = Math.round(BELT_H * dpr);
    const ctx = this.belt.getContext('2d')!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, BELT_H);
    const bins = beltBins(sec);
    if (!bins.length) return;
    const pw = w - MARGIN.l - MARGIN.r;
    const lat0 = bins[0]!.lat - 2.5;
    const span = 5 * bins.length;
    const x = (lat: number) => MARGIN.l + ((lat - lat0) / span) * pw;
    const laneH = (BELT_H - MARGIN.t - MARGIN.b) / 2;
    ctx.font = '11px system-ui, sans-serif';
    const lanes = [
      { key: 'upper' as const, colour: '#f08a5d', y: MARGIN.t + laneH / 2, name: 'Upper' },
      { key: 'deep' as const, colour: '#6fb6f2', y: MARGIN.t + laneH * 1.5, name: 'Deep' },
    ];
    for (const lane of lanes) {
      const half = (v: number) => Math.min(1, Math.abs(v) / VMAX) * (laneH / 2 - 2);
      ctx.fillStyle = 'rgba(255,255,255,0.04)';
      ctx.fillRect(MARGIN.l, lane.y - laneH / 2 + 1, pw, laneH - 2);
      ctx.fillStyle = '#a3a9b4';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(lane.name, MARGIN.l - 6, lane.y);
      // The ribbon, between the bin centres; a bin without water breaks it.
      ctx.fillStyle = `${lane.colour}99`;
      let run: BeltBin[] = [];
      const flush = () => {
        if (run.length) {
          ctx.beginPath();
          run.forEach((b, i) => ctx[i ? 'lineTo' : 'moveTo'](x(b.lat), lane.y - half(b[lane.key])));
          [...run].reverse().forEach((b) => ctx.lineTo(x(b.lat), lane.y + half(b[lane.key])));
          ctx.closePath();
          ctx.fill();
        }
        run = [];
      };
      for (const b of bins) {
        if (Number.isFinite(b[lane.key])) run.push(b);
        else flush();
      }
      flush();
      // Arrowheads every other bin, pointing the way the water goes.
      ctx.fillStyle = lane.colour;
      ctx.strokeStyle = '#10131a';
      bins.forEach((b, i) => {
        const v = b[lane.key];
        if (i % 2 || !Number.isFinite(v) || Math.abs(v) < 0.5) return;
        const s = v >= 0 ? 1 : -1;
        const cx = x(b.lat);
        const size = 3 + 5 * Math.min(1, Math.abs(v) / VMAX);
        ctx.beginPath();
        ctx.moveTo(cx + s * size, lane.y);
        ctx.lineTo(cx - s * size * 0.6, lane.y - size);
        ctx.lineTo(cx - s * size * 0.6, lane.y + size);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      });
    }
    const mark = x(this.ocean!.section.lat);
    ctx.strokeStyle = 'rgba(255,255,255,0.5)';
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(mark, MARGIN.t);
    ctx.lineTo(mark, BELT_H - MARGIN.b);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#a3a9b4';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const lat of LAT_TICKS) ctx.fillText(`${Math.abs(lat)}°${lat < 0 ? 'S' : lat > 0 ? 'N' : ''}`, x(lat), BELT_H - MARGIN.b + 5);
  }

  private paintHeat(sec: SectionField): void {
    const w = Math.max(240, this.strengthBox.clientWidth || 440);
    const dpr = window.devicePixelRatio || 1;
    this.heat.style.width = `${w}px`;
    this.heat.style.height = `${HEAT_H}px`;
    this.heat.width = Math.round(w * dpr);
    this.heat.height = Math.round(HEAT_H * dpr);
    const ctx = this.heat.getContext('2d')!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, HEAT_H);
    const pw = w - MARGIN.l - MARGIN.r;
    const ph = HEAT_H - MARGIN.t - MARGIN.b;
    const dlat = sec.lat[1]! - sec.lat[0]!;
    const lat0 = sec.lat[0]! - dlat / 2;
    const span = dlat * sec.lat.length;
    const zMax = sqrtDepth(sec.edges[sec.edges.length - 1]!);
    const x = (lat: number) => MARGIN.l + ((lat - lat0) / span) * pw;
    const y = (z: number) => MARGIN.t + (sqrtDepth(z) / zMax) * ph;
    ctx.fillStyle = '#10131a';
    ctx.fillRect(MARGIN.l, MARGIN.t, pw, ph);
    // Each level is drawn as a band from its top edge to its bottom edge, in the value at its bottom.
    for (let k = 0; k < sec.psi.length; k++) {
      const y0 = y(sec.edges[k]!);
      const y1 = y(sec.edges[k + 1]!);
      for (let j = 0; j < sec.lat.length; j++) {
        const v = sec.psi[k]![j]!;
        if (!Number.isFinite(v)) continue;
        const [r, g, b] = psiColour(v, VMAX);
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        const xa = x(sec.lat[j]! - dlat / 2);
        ctx.fillRect(xa, y0, x(sec.lat[j]! + dlat / 2) - xa + 0.6, y1 - y0 + 0.6);
      }
    }
    ctx.strokeStyle = 'rgba(255,255,255,0.7)';
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    const xs = x(this.ocean!.section.lat);
    ctx.moveTo(xs, MARGIN.t);
    ctx.lineTo(xs, MARGIN.t + ph);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#a3a9b4';
    ctx.font = '11px system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const z of DEPTH_TICKS) ctx.fillText(`${z}`, MARGIN.l - 6, y(z));
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const lat of LAT_TICKS) ctx.fillText(`${Math.abs(lat)}°${lat < 0 ? 'S' : lat > 0 ? 'N' : ''}`, x(lat), MARGIN.t + ph + 5);
  }

  private drawStrength(sec: SectionField): void {
    this.strengthChart?.destroy();
    this.strengthBox.innerHTML = '';
    const { sv } = sectionStrength(sec);
    const opts: uPlot.Options = {
      width: Math.max(240, this.strengthBox.clientWidth || 440),
      height: 130,
      legend: { show: false },
      cursor: { drag: { x: false, y: false } },
      scales: { x: { time: false }, y: { range: (_u, lo, hi) => [Math.min(0, lo), Math.max(hi * 1.1, 1)] } },
      axes: [
        { ...AXIS, values: (_u, v) => v.map((l) => `${Math.abs(l)}°${l < 0 ? 'S' : l > 0 ? 'N' : ''}`) },
        { ...AXIS, size: 44 },
      ],
      series: [{}, { stroke: '#f08a5d', width: 2, points: { show: false }, spanGaps: false }],
    };
    this.strengthChart = new uPlot(opts, [sec.lat, sv.map((x) => (Number.isFinite(x) ? x : null))], this.strengthBox);
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
