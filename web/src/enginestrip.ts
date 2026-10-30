// The global engine strip (docs/PROPOSALS-v2.md F8): the frame's area-weighted global means in
// plain words, symbol second, each with its formula as a tooltip and a link to its (i) panel.
import { stripItems, type Zonal } from './zonal';
import type { Frame } from './modes';

export class EngineStrip {
  constructor(
    private readonly root: HTMLElement,
    private readonly onInfo: (layer: string, opener: HTMLElement) => void,
  ) {
    root.setAttribute('role', 'group');
    root.setAttribute('aria-label', 'Global engine');
    this.update(null, 'year', '');
  }

  /** Show a frame's or date's global means; `z` null gives dashes. `what` names it, e.g. "July" or a date. */
  update(z: Zonal | null, frame: Frame | null, what: string): void {
    const head = document.createElement('div');
    head.className = 'es-head';
    head.textContent = what ? `Global means · ${what}` : 'Global means';
    const items = stripItems(z, frame).map((it) => {
      const box = document.createElement('div');
      box.className = 'es-item';
      box.dataset.id = it.id;
      box.title = `${it.label} (${it.symbol}): ${it.formula}`;
      const label = document.createElement('span');
      label.className = 'es-label';
      label.textContent = it.label;
      const value = document.createElement('span');
      value.className = 'es-value';
      value.textContent = it.value;
      const symbol = document.createElement('span');
      symbol.className = 'es-symbol';
      symbol.textContent = it.symbol;
      box.append(label, value, symbol);
      if (it.layer) {
        const layer = it.layer;
        const info = document.createElement('button');
        info.type = 'button';
        info.className = 'info-button es-info';
        info.textContent = 'i';
        info.setAttribute('aria-label', `About ${it.label}`);
        info.addEventListener('click', () => this.onInfo(layer, info));
        box.append(info);
      }
      return box;
    });
    this.root.replaceChildren(head, ...items);
  }
}
