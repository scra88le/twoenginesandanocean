// "How the engine works": the overview infographic (docs/PROPOSALS-v2.md F13).
//
// A hand-authored SVG (src/overview/desktop.svg) whose value slots (`data-slot`) are filled from the
// Year frame's zonal file, the 1991-2020 annual mean. Every number is computed by the pipeline
// (`pipeline.zonal`); this file only rounds and words it. Elements carry `data-part`
// (engine1, engine2 or ocean) and `data-step` (the tour card they open), so the SVG is the one
// place that says what leads where. Values go in with `textContent`, never as HTML.
import type { Zonal, ZonalGlobal } from './zonal';

export const PARTS = ['engine1', 'engine2', 'ocean'] as const;
export type Part = (typeof PARTS)[number];

/** The highlight chips and the two or three sentences beside the graphic. No numbers here. */
export const CHIPS: { id: Part | 'all'; label: string; text: string }[] = [
  {
    id: 'all',
    label: 'All',
    text: 'Sunlight warms the surface and the tropics. Two engines turn part of that heat into motion, and the ocean stores and carries some of it. Choose a part to highlight it, or click any part to see it on the map.',
  },
  {
    id: 'engine1',
    label: 'Engine one',
    text: 'Between the hot surface and the cold sky, rising warm air is a heat engine. Its output is limited by the Carnot ceiling, and the most power it can make comes from lifting about half of the sunlight the surface absorbs.',
  },
  {
    id: 'engine2',
    label: 'Engine two',
    text: 'The tropics absorb more heat than they radiate and the high latitudes less. The air carries the difference poleward, and the winds that do it lose their motion as friction, which turns back into heat.',
  },
  {
    id: 'ocean',
    label: 'The ocean',
    text: 'The ocean is a battery and a conveyor. It stores heat in summer and gives it back in winter, and its currents carry heat poleward, most of it at low latitudes.',
  },
];

type Key = keyof ZonalGlobal;
interface Slot {
  text: (v: number) => string; // rounded for reading
  exact: (v: number) => string; // for the tooltip
}

const whole = (v: number) => String(Math.round(v)).replace('-', '−');
const wm2 = (digits: number): Slot => ({
  text: (v) => `≈ ${v.toFixed(digits)} W m⁻²`,
  exact: (v) => `${v.toFixed(2)} W m⁻²`,
});
const kelvin: Slot = {
  text: (v) => `${whole(v)} K (${whole(v - 273.15)} °C)`,
  exact: (v) => `${v.toFixed(2)} K (${(v - 273.15).toFixed(2)} °C)`,
};
const pw: Slot = { text: (v) => `up to ${v.toFixed(1)} PW`, exact: (v) => `${v.toFixed(3)} PW` };

/** How each `data-slot` is written. The keys are the Year frame's `global` block. */
export const SLOTS: Partial<Record<Key, Slot>> = {
  asr_toa: wm2(0),
  olr: wm2(0),
  asr_atm: wm2(0),
  asr_sfc: wm2(0),
  lw_up: wm2(0),
  j_conv: wm2(0),
  lh: wm2(0),
  sh: wm2(0),
  diss_bl: wm2(1),
  precip: { text: (v) => `≈ ${v.toFixed(1)} mm day⁻¹`, exact: (v) => `${v.toFixed(3)} mm day⁻¹` },
  carnot: { text: (v) => `≈ ${Math.round(v)} %`, exact: (v) => `${v.toFixed(2)} %` },
  t_skin: kelvin,
  t_r: kelvin,
  pw_atm: pw,
  pw_ocean: pw,
};

export interface SlotValue {
  text: string;
  exact: string;
}

/** The filled slots of a zonal file; a slot the file doesn't have (or no file at all) is null. */
export function slotValues(z: Zonal | null): Record<string, SlotValue | null> {
  const out: Record<string, SlotValue | null> = {};
  for (const [key, slot] of Object.entries(SLOTS) as [Key, Slot][]) {
    const v = z?.global[key];
    out[key] = typeof v === 'number' && Number.isFinite(v) ? { text: slot.text(v), exact: slot.exact(v) } : null;
  }
  return out;
}

/** The slots that are arrows, by unit family: W m⁻² flows share one width scale, PW transports another. */
export const FAMILIES: Record<string, Key[]> = {
  wm2: ['asr_toa', 'olr', 'asr_sfc', 'lw_up', 'j_conv'],
  pw: ['pw_atm', 'pw_ocean'],
};

/**
 * Arrow stroke widths in px: proportional to the value within a family, the family's largest
 * flow taking `maxPx`, never thinner than `minPx` so a small flow stays visible. Missing values are absent.
 */
export function fluxWidths(g: Partial<ZonalGlobal> | undefined, maxPx = 20, minPx = 2): Record<string, number> {
  const out: Record<string, number> = {};
  for (const keys of Object.values(FAMILIES)) {
    const vals = keys.map((k) => g?.[k]).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
    const top = Math.max(...vals.map(Math.abs), 0);
    if (top <= 0) continue;
    for (const k of keys) {
      const v = g?.[k];
      if (typeof v === 'number' && Number.isFinite(v)) out[k] = Math.max(minPx, (Math.abs(v) / top) * maxPx);
    }
  }
  return out;
}

export const SEEN_KEY = 'ehe.overview.seen';

/**
 * Whether the overview opens by itself at load. `?overview=1` always opens it; `?overview=0` and
 * `?tour=N` (the tour takes over) never do; otherwise it opens until the visitor has dismissed
 * it once. `readSeen` returns the stored value and may throw (storage blocked): then it opens,
 * once per page load, since this is asked once per load.
 */
export function shouldAutoShow(params: URLSearchParams, readSeen: () => string | null): boolean {
  const flag = params.get('overview');
  if (flag === '1') return true;
  if (flag === '0' || params.has('tour')) return false;
  try {
    return readSeen() !== '1';
  } catch {
    return true;
  }
}

/** The stored "seen" flag; throws if storage is unavailable. */
export const readSeen = (): string | null => localStorage.getItem(SEEN_KEY);

/** Remember that the overview was dismissed. A browser that refuses storage just shows it again next load. */
export function markSeen(store: Pick<Storage, 'setItem'> = localStorage): void {
  try {
    store.setItem(SEEN_KEY, '1');
  } catch {
    // storage unavailable: shown once per page load instead
  }
}

export interface OverviewOptions {
  /** Open the tour card with this id prefix ("07"). The overview has closed itself first. */
  onStep: (step: string) => void;
  /** "Take the tour": start at the first card. */
  onTour: () => void;
}

export class Overview {
  readonly dialog: HTMLDialogElement;
  private readonly svg: SVGSVGElement;
  private readonly figure: HTMLElement;
  private readonly list: HTMLOListElement;
  private readonly explain: HTMLElement;
  private readonly note: HTMLElement;
  private readonly chips: HTMLButtonElement[] = [];
  private readonly textToggle: HTMLButtonElement;
  private opener: HTMLElement | null = null;
  private handoff = false; // closing to open the tour: the tour takes focus, not the opener

  constructor(svgText: string, private readonly opts: OverviewOptions) {
    const d = (this.dialog = document.createElement('dialog'));
    d.id = 'overview';
    d.setAttribute('aria-labelledby', 'ov-heading');
    d.innerHTML = `
      <div class="ov-head">
        <h2 id="ov-heading">How the engine works</h2>
        <button type="button" class="ov-close" aria-label="Close">×</button>
      </div>
      <div class="ov-chips" role="group" aria-label="Highlight a part"></div>
      <p class="ov-explain" aria-live="polite"></p>
      <div class="ov-figure"></div>
      <ol class="ov-list" hidden></ol>
      <p class="ov-note"></p>
      <div class="ov-foot">
        <button type="button" class="ov-text" aria-pressed="false">Read as text</button>
        <span class="ov-spacer"></span>
        <button type="button" class="ov-explore">Explore the map</button>
        <button type="button" class="ov-tour">Take the tour</button>
      </div>`;
    this.figure = d.querySelector('.ov-figure')!;
    this.list = d.querySelector('.ov-list')!;
    this.explain = d.querySelector('.ov-explain')!;
    this.note = d.querySelector('.ov-note')!;
    this.textToggle = d.querySelector('.ov-text')!;

    const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');
    if (doc.querySelector('parsererror')) throw new Error('overview svg is not valid XML');
    this.svg = document.importNode(doc.documentElement, true) as unknown as SVGSVGElement;
    this.figure.append(this.svg);

    const chipRow = d.querySelector('.ov-chips')!;
    for (const c of CHIPS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'ov-chip';
      b.textContent = c.label;
      b.dataset.chip = c.id;
      b.addEventListener('click', () => this.highlight(c.id));
      chipRow.append(b);
      this.chips.push(b);
    }
    this.highlight('all');

    for (const el of this.elements()) {
      el.addEventListener('click', () => this.choose(el));
      el.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        this.choose(el);
      });
    }
    d.querySelector('.ov-close')!.addEventListener('click', () => d.close());
    d.querySelector('.ov-explore')!.addEventListener('click', () => d.close());
    d.querySelector('.ov-tour')!.addEventListener('click', () => {
      this.handoff = true;
      d.close();
      this.opts.onTour();
    });
    this.textToggle.addEventListener('click', () => this.setText(this.list.hidden === true));
    d.addEventListener('close', () => {
      // the 'close' event is queued, so it arrives after the tour has taken focus
      if (this.handoff) this.handoff = false;
      else (this.opener ?? document.querySelector<HTMLElement>('.maplibregl-canvas'))?.focus();
    });
    d.addEventListener('click', (e) => e.target === d && d.close()); // backdrop
    document.body.append(d);
    this.fill(null);
  }

  get isOpen(): boolean {
    return this.dialog.open;
  }

  /** Show the overview. `zonal` is the Year frame's file, or null when no climatology is published. */
  open(zonal: Zonal | null, opener: HTMLElement | null): void {
    this.opener = opener;
    this.fill(zonal);
    if (!this.dialog.open) this.dialog.showModal();
    this.dialog.querySelector<HTMLElement>('.ov-tour')!.focus();
  }

  close(): void {
    this.dialog.close();
  }

  /** Refill the slots, e.g. when the file arrives after the overview opened. */
  fill(zonal: Zonal | null): void {
    const values = slotValues(zonal);
    for (const s of this.svg.querySelectorAll<SVGElement>('[data-slot]')) {
      s.textContent = values[s.dataset.slot!]?.text ?? '—';
    }
    const widths = fluxWidths(zonal?.global);
    for (const line of this.svg.querySelectorAll<SVGElement>('[data-flux]')) {
      const w = widths[line.dataset.flux!];
      line.classList.toggle('ov-nodata', w === undefined);
      line.setAttribute('stroke-width', String(w ?? 4));
    }
    for (const el of this.elements()) {
      const parts = this.slotsOf(el).map((s) => {
        const v = values[s.dataset.slot!];
        return v ? { name: s.dataset.name ?? '', text: v.text, exact: v.exact } : null;
      });
      const label = el.dataset.label!;
      const known = parts.filter((p): p is NonNullable<typeof p> => p !== null);
      const spoken = known.map((p) => (p.name === label ? p.text : `${p.name} ${p.text}`));
      const step = Number(el.dataset.step);
      el.setAttribute('aria-label', `${label}${spoken.length ? `, ${spoken.join(', ')}` : ''}: open tour step ${step}`);
      // the tooltip carries the exact values
      const tip = [label, ...known.map((p) => `${p.name}: ${p.exact}`)].join('\n');
      el.querySelector(':scope > title')!.textContent = tip;
    }
    this.note.textContent = zonal
      ? 'ERA5, 1991–2020 annual mean. Rounded for reading; hover for the exact values.'
      : 'The 1991–2020 climatology is not published yet, so no values are shown.';
    this.buildList();
  }

  /** Highlight one part (the others dim, and its outlines show) or all of them. */
  highlight(id: Part | 'all'): void {
    this.svg.dataset.focus = id;
    this.chips.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.chip === id)));
    this.explain.textContent = CHIPS.find((c) => c.id === id)!.text;
  }

  /** Swap the graphic for the same elements as an ordered list. */
  setText(on: boolean): void {
    this.list.hidden = !on;
    this.figure.hidden = on;
    this.textToggle.setAttribute('aria-pressed', String(on));
    this.textToggle.textContent = on ? 'Show the graphic' : 'Read as text';
  }

  private elements(): SVGElement[] {
    return [...this.svg.querySelectorAll<SVGElement>('[data-el]')];
  }

  private slotsOf(el: Element): SVGElement[] {
    return [...el.querySelectorAll<SVGElement>('[data-slot]')];
  }

  private choose(el: SVGElement): void {
    this.handoff = true;
    this.dialog.close();
    this.opts.onStep(el.dataset.step!);
  }

  private buildList(): void {
    this.list.replaceChildren(
      // in tour order, which is the order to read them in (the drawing has surplus last)
      ...this.elements().sort((a, b) => Number(a.dataset.step) - Number(b.dataset.step)).map((el) => {
        const li = document.createElement('li');
        li.dataset.listEl = el.dataset.el;
        const h = document.createElement('strong');
        h.textContent = el.dataset.label!;
        const p = document.createElement('span');
        p.className = 'ov-list-desc';
        p.textContent = ` ${el.querySelector(':scope > desc')?.textContent?.replace(/\s*Opens step.*$/, '') ?? ''}`;
        const vals = this.slotsOf(el)
          .filter((s) => s.textContent !== '—')
          .map((s) => `${s.dataset.name}: ${s.textContent}`);
        const v = document.createElement('span');
        v.className = 'ov-list-values';
        v.textContent = vals.length ? ` ${vals.join('; ')}.` : '';
        const go = document.createElement('button');
        go.type = 'button';
        go.className = 'ov-list-go';
        go.textContent = `Open tour step ${Number(el.dataset.step)}`;
        go.setAttribute('aria-label', `${el.dataset.label}: open tour step ${Number(el.dataset.step)}`);
        go.addEventListener('click', () => this.choose(el));
        li.append(h, p, v, ' ', go);
        return li;
      }),
    );
  }
}
