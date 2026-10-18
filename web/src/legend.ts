import { cssGradient } from './colormaps';
import { formatReading, prettyUnits } from './format';
import type { LayerMeta } from './manifest';
import { ticks, type DisplayScale } from './scale';

export class Legend {
  private readonly value: HTMLElement;
  private meta?: LayerMeta;

  constructor(private readonly root: HTMLElement) {
    root.innerHTML = `
      <div class="legend-title"></div>
      <div class="legend-bar" role="img"></div>
      <div class="legend-ticks"></div>
      <div class="legend-value" aria-live="polite">Hover over the map for a value</div>`;
    this.value = root.querySelector('.legend-value')!;
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
  }

  showValue(v: number | null, masked = false): void {
    if (!this.meta) return;
    if (v === null) this.value.textContent = 'Hover over the map for a value';
    else if (masked) this.value.textContent = 'Not shown here (masked)';
    else this.value.textContent = formatReading(v, this.meta.units, this.meta.encode);
  }
}
