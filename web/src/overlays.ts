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
