// Overlay controls at the top of the layer menu: wind particles (on or off, and their level),
// transport arrows, and the timescale switch.
import type { Manifest } from './manifest';
import { MODES, MODE_LABELS, type Mode } from './modes';
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

  /** Set the controls (without firing onChange), for the tour. Unbuilt levels are ignored. */
  set(choice: ParticleChoice): void {
    if (!this.select.disabled && !this.select.querySelector<HTMLOptionElement>(`option[value="${choice.level}"]`)!.disabled) {
      this.select.value = choice.level;
    }
    this.checkbox.checked = choice.on && !this.checkbox.disabled;
  }
}

/** The transport arrows toggle (flux_e). */
export class ArrowsSwitch {
  readonly element: HTMLDivElement;
  private readonly checkbox: HTMLInputElement;

  constructor(m: Manifest, initial: boolean, onChange: (on: boolean) => void) {
    this.element = document.createElement('div');
    this.element.className = 'overlay-row arrows-row';
    this.element.innerHTML = `
      <label class="overlay-toggle"><input type="checkbox" class="arrows-on" /> Transport arrows</label>`;
    this.checkbox = this.element.querySelector('.arrows-on')!;
    const built = m.built_layers.includes('flux_e') && !!m.layers.flux_e?.uv_encode;
    this.checkbox.checked = initial && built;
    this.checkbox.disabled = !built;
    if (!built) this.element.title = 'No transport data has been published yet';
    this.checkbox.addEventListener('change', () => onChange(this.checkbox.checked));
  }

  get on(): boolean {
    return this.checkbox.checked;
  }

  set(on: boolean): void {
    this.checkbox.checked = on && !this.checkbox.disabled;
  }
}

/** The timescale switch: Climate, Today or Today vs normal. Unavailable modes are disabled. */
export class ModeSwitch {
  readonly element: HTMLFieldSetElement;
  private readonly radios = new Map<Mode, HTMLInputElement>();

  constructor(initial: Mode, onChange: (mode: Mode) => void) {
    this.element = document.createElement('fieldset');
    this.element.className = 'mode-switch';
    this.element.innerHTML = '<legend>Timescale</legend><div class="mode-row"></div>';
    const row = this.element.querySelector('.mode-row')!;
    for (const mode of MODES) {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'mode';
      input.value = mode;
      input.className = `mode-${mode}`;
      input.checked = mode === initial;
      input.addEventListener('change', () => input.checked && onChange(mode));
      label.append(input, ` ${MODE_LABELS[mode]}`);
      row.append(label);
      this.radios.set(mode, input);
    }
  }

  get mode(): Mode {
    return MODES.find((m) => this.radios.get(m)!.checked) ?? 'today';
  }

  /** Show the mode in use and disable the ones the active layer can't show. */
  update(mode: Mode, available: Mode[]): void {
    for (const [m, input] of this.radios) {
      input.checked = m === mode;
      input.disabled = !available.includes(m);
      input.parentElement!.title = input.disabled ? 'Not available for this layer' : '';
    }
  }
}
