import { cssGradient } from './colormaps';
import { formatReading, prettyUnits } from './format';
import { maskLabel } from './info';
import type { LayerMeta } from './manifest';
import { ticks, type DisplayScale } from './scale';

export class Legend {
  private readonly value: HTMLElement;
  private readonly wind: HTMLElement;
  private meta?: LayerMeta;

  constructor(private readonly root: HTMLElement) {
    root.innerHTML = `
      <div class="legend-title"></div>
      <div class="legend-bar" role="img"></div>
      <div class="legend-ticks"></div>
      <div class="legend-notes"></div>
      <div class="legend-value" aria-live="polite">Hover over the map for a value</div>
      <div class="legend-wind" hidden></div>`;
    this.value = root.querySelector('.legend-value')!;
    this.wind = root.querySelector('.legend-wind')!;
  }

  show(meta: LayerMeta, scale: DisplayScale): void {
    this.meta = meta;
    const units = prettyUnits(meta.units);
    const title = this.root.querySelector('.legend-title')!;
    title.textContent = `${meta.title} `;
    const unitSpan = document.createElement('span');
    unitSpan.className = 'units';
    unitSpan.textContent = `(${units})`;
    title.append(unitSpan);
    const bar = this.root.querySelector<HTMLElement>('.legend-bar')!;
    bar.style.background = cssGradient(meta.colour);
    bar.setAttribute('aria-label', `Colour scale from ${scale.lo} to ${scale.hi} ${units}${meta.log ? ', logarithmic' : ''}`);
    this.root.querySelector('.legend-ticks')!.innerHTML = ticks(scale)
      .map((t) => `<span style="left:${(t.t * 100).toFixed(2)}%">${t.label}</span>`)
      .join('');
    const notes = this.root.querySelector('.legend-notes')!;
    notes.innerHTML = '';
    const note = (cls: string, text: string) => {
      const p = document.createElement('div');
      p.className = `legend-note ${cls}`;
      p.textContent = text;
      notes.append(p);
    };
    if (meta.info.mask) note('note-mask', `Grey: ${maskLabel(meta.info.mask).toLowerCase()}`);
    if (meta.hatch_zero) note('note-hatch', 'Hatched: clamped at zero');
    if (meta.display === 'auto') note('note-auto', "Colour range: this day's 2nd–98th percentile");
    this.showValue(null);
  }

  /** The particle line: what the particles show, or the wind under the cursor. null hides it. */
  showWind(text: string | null): void {
    this.wind.hidden = text === null;
    this.wind.textContent = text ?? '';
  }

  showMessage(text: string): void {
    this.value.textContent = text;
  }

  showValue(v: number | null, masked = false): void {
    if (!this.meta) return;
    if (v === null) this.value.textContent = 'Hover over the map for a value';
    else if (masked)
      this.value.textContent = `Not shown here: ${maskLabel(this.meta.info.mask ?? 'masked').toLowerCase()}`;
    else this.value.textContent = formatReading(v, this.meta.units, this.meta.encode);
  }
}
