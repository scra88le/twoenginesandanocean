// Overlay controls at the top of the layer menu: wind particles (on or off, and their level),
// transport arrows, and the timescale switch.
import type { Manifest } from './manifest';
import { MODES, MODE_LABELS, type Mode } from './modes';
import { AVG_LABELS, LIMB_CHOICES, type OceanAvg, type OceanChoice, type OceanLimbs } from './ocean';
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

/** The ocean overlay: on or off, which limbs, and daily or the 30-day mean. */
export class OceanControls {
  readonly element: HTMLDivElement;
  private readonly checkbox: HTMLInputElement;
  private readonly limbs: HTMLSelectElement;
  private readonly avg: HTMLSelectElement;

  constructor(
    m: Manifest,
    initial: OceanChoice,
    onChange: (choice: OceanChoice) => void,
    onInfo: (opener: HTMLElement) => void,
    onTrend: () => void,
    initialBelt = false,
    onBelt: (on: boolean) => void = () => undefined,
  ) {
    this.element = document.createElement('div');
    this.element.className = 'overlay-row ocean-row';
    this.element.innerHTML = `
      <label class="overlay-toggle"><input type="checkbox" class="ocean-on" /> Ocean overturning</label>
      <select class="ocean-select ocean-limbs" aria-label="Which limbs of the overturning"></select>
      <select class="ocean-select ocean-avg" aria-label="Daily or 30-day mean currents"></select>
      <label class="overlay-toggle ocean-belt-toggle" title="Schematic arrows down the middle of the Atlantic: each limb's net transport across the whole basin, per 5° of latitude"><input type="checkbox" class="ocean-belt" /> Belt arrows</label>
      <button type="button" class="ocean-trend" aria-pressed="false" aria-controls="amoc">AMOC section</button>
      <button type="button" class="info-button ocean-info" aria-label="About the ocean overturning">i</button>`;
    this.checkbox = this.element.querySelector('.ocean-on')!;
    this.limbs = this.element.querySelector('.ocean-limbs')!;
    this.avg = this.element.querySelector('.ocean-avg')!;
    for (const [value, { label }] of Object.entries(LIMB_CHOICES)) this.limbs.append(new Option(label, value));
    for (const [value, label] of Object.entries(AVG_LABELS)) this.avg.append(new Option(label, value));
    const built = !!m.ocean && Object.keys(m.ocean.dates).length > 0;
    this.limbs.value = initial.limbs;
    this.avg.value = initial.avg;
    this.checkbox.checked = initial.on && built;
    for (const el of [this.checkbox, this.limbs, this.avg]) {
      el.disabled = !built;
      el.addEventListener('change', () => onChange(this.choice));
    }
    const belt = this.element.querySelector<HTMLInputElement>('.ocean-belt')!;
    belt.checked = initialBelt && built;
    belt.disabled = !built;
    belt.addEventListener('change', () => onBelt(belt.checked));
    const trend = this.element.querySelector<HTMLButtonElement>('.ocean-trend')!;
    trend.disabled = !built;
    trend.addEventListener('click', onTrend);
    const info = this.element.querySelector<HTMLButtonElement>('.ocean-info')!;
    info.hidden = !m.ocean;
    info.addEventListener('click', () => onInfo(info));
    if (!built) this.element.title = 'No ocean currents have been published yet';
  }

  get choice(): OceanChoice {
    return { on: this.checkbox.checked, limbs: this.limbs.value as OceanLimbs, avg: this.avg.value as OceanAvg };
  }

  /** Set the controls (without firing onChange), for the tour. */
  set(choice: OceanChoice): void {
    this.checkbox.checked = choice.on && !this.checkbox.disabled;
    this.limbs.value = choice.limbs;
    this.avg.value = choice.avg;
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
