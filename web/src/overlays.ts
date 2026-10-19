// Overlay controls at the top of the layer menu: wind particles on or off, and their level.
import type { Manifest } from './manifest';
import { LEVEL_LABELS, WIND_LEVELS, type WindLevel } from './wind';

export interface ParticleChoice {
  on: boolean;
  level: WindLevel;
}

/** Built wind levels, in menu order. */
export function builtLevels(m: Manifest): WindLevel[] {
  return WIND_LEVELS.filter((l) => m.built_layers.includes(l) && m.layers[l]?.uv_encode);
}

export class OverlayControls {
  readonly element: HTMLFieldSetElement;
  private readonly checkbox: HTMLInputElement;
  private readonly select: HTMLSelectElement;

  constructor(
    m: Manifest,
    initial: ParticleChoice,
    private readonly onChange: (choice: ParticleChoice) => void,
  ) {
    const built = builtLevels(m);
    this.element = document.createElement('fieldset');
    this.element.className = 'overlays';
    this.element.innerHTML = `
      <legend>Overlays</legend>
      <div class="overlay-row">
        <label class="overlay-toggle"><input type="checkbox" class="particles-on" /> Wind particles</label>
        <select class="particles-level" aria-label="Wind level"></select>
      </div>`;
    this.checkbox = this.element.querySelector('.particles-on')!;
    this.select = this.element.querySelector('.particles-level')!;
    for (const level of WIND_LEVELS) {
      const opt = document.createElement('option');
      opt.value = level;
      opt.textContent = built.includes(level) ? LEVEL_LABELS[level] : `${LEVEL_LABELS[level]} (not available yet)`;
      opt.disabled = !built.includes(level);
      this.select.append(opt);
    }
    const level = built.includes(initial.level) ? initial.level : built[0];
    if (level) this.select.value = level;
    this.checkbox.checked = initial.on && !!level;
    this.checkbox.disabled = !level;
    this.select.disabled = !level;
    if (!level) this.checkbox.parentElement!.title = 'No wind data has been published yet';
    this.checkbox.addEventListener('change', () => this.onChange(this.choice));
    this.select.addEventListener('change', () => this.onChange(this.choice));
  }

  get choice(): ParticleChoice {
    return { on: this.checkbox.checked, level: this.select.value as WindLevel };
  }
}

/** The anomaly switch: shows the active raster as the difference from its 1991-2020 mean. */
export class AnomalySwitch {
  readonly element: HTMLDivElement;
  private readonly checkbox: HTMLInputElement;
  private readonly note: HTMLElement;

  constructor(m: Manifest, initial: boolean, onChange: (on: boolean) => void) {
    this.element = document.createElement('div');
    this.element.className = 'overlay-row anomaly-row';
    const period = m.clim?.period.replace('-', '–') ?? '1991–2020';
    this.element.innerHTML = `
      <label class="overlay-toggle"><input type="checkbox" class="anomaly-on" /> Anomaly vs ${period}</label>
      <span class="anomaly-note"></span>`;
    this.checkbox = this.element.querySelector('.anomaly-on')!;
    this.note = this.element.querySelector('.anomaly-note')!;
    const published = !!m.clim;
    this.checkbox.checked = initial && published;
    this.checkbox.disabled = !published;
    if (!published) this.note.textContent = 'Climatology not published yet';
    this.checkbox.addEventListener('change', () => onChange(this.checkbox.checked));
  }

  get on(): boolean {
    return this.checkbox.checked;
  }

  /** Say when the switch is on but the active layer has no anomaly. */
  setLayerHasAnomaly(has: boolean): void {
    if (this.checkbox.disabled) return;
    this.note.textContent = this.on && !has ? 'Not for this layer' : '';
  }
}
