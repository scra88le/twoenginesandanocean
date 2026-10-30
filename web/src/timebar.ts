// Time bar. Today and Today vs normal: the last 90 available days, newest on the right, with
// play / pause / step. Climate: twelve months and a separate Year stop; play cycles January to
// December and loops, skipping Year.
import { FRAMES, frameName, playFrame, stepFrame, type Frame } from './modes';

export const stepIndex = (i: number, delta: number, n: number) => Math.min(n - 1, Math.max(0, i + delta));

/** Dates within `radius` days of index i, nearest first (excluding i itself). */
export function nearbyDates(dates: string[], i: number, radius: number): string[] {
  const out: string[] = [];
  for (let k = 1; k <= radius; k++) {
    for (const j of [i + k, i - k]) if (j >= 0 && j < dates.length) out.push(dates[j]!);
  }
  return out;
}

const PLAY_INTERVAL_MS = 800;
const MONTHS = FRAMES.length - 1; // the slider covers the months; Year has its own button

export type Kind = 'dates' | 'frames';

export class TimeBar {
  private index: number;
  private frame: Frame;
  private kind: Kind = 'dates';
  private playing = false;
  private readonly range: HTMLInputElement;
  private readonly label: HTMLElement;
  private readonly note: HTMLElement;
  private readonly play: HTMLButtonElement;
  private readonly year: HTMLButtonElement;

  constructor(
    private readonly root: HTMLElement,
    private readonly dates: string[],
    initial: string,
    private readonly onChange: (date: string) => Promise<void>,
    private readonly onFrame: (frame: Frame) => Promise<void> = async () => undefined,
    initialFrame: Frame = 'year',
  ) {
    this.index = Math.max(0, dates.indexOf(initial));
    this.frame = initialFrame;
    root.innerHTML = `
      <button type="button" class="tb-step" data-step="-1" aria-label="Previous day">‹</button>
      <button type="button" class="tb-play" aria-label="Play">▶</button>
      <button type="button" class="tb-step" data-step="1" aria-label="Next day">›</button>
      <input type="range" class="tb-range" min="0" step="1" aria-label="Date" />
      <button type="button" class="tb-year" aria-pressed="false" hidden>Year</button>
      <div class="tb-text"><span class="tb-date" aria-live="polite"></span>
        <span class="tb-note">ERA5, about 6 days behind real time</span></div>`;
    this.range = root.querySelector('.tb-range')!;
    this.label = root.querySelector('.tb-date')!;
    this.note = root.querySelector('.tb-note')!;
    this.play = root.querySelector('.tb-play')!;
    this.year = root.querySelector('.tb-year')!;
    for (const b of root.querySelectorAll<HTMLButtonElement>('.tb-step')) {
      b.addEventListener('click', () => this.step(Number(b.dataset.step)));
    }
    this.play.addEventListener('click', () => (this.playing ? this.pause() : void this.start()));
    this.range.addEventListener('input', () => {
      this.pause();
      void this.go(Number(this.range.value));
    });
    this.year.addEventListener('click', () => {
      this.pause();
      void this.goFrame('year');
    });
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      // Arrow keys belong to whatever has focus: the menu, the slider, the map canvas.
      const t = e.target as HTMLElement;
      if (t !== document.body && !t.matches('.tb-step, .tb-play, .tb-year')) return;
      e.preventDefault();
      this.step(e.key === 'ArrowLeft' ? -1 : 1);
    });
    this.setKind('dates');
  }

  get date(): string {
    return this.dates[this.index]!;
  }

  get currentFrame(): Frame {
    return this.frame;
  }

  /** Switch between the 90 days and the 13 climate frames (without firing the callbacks). */
  setKind(kind: Kind): void {
    if (kind !== this.kind) this.pause();
    this.kind = kind;
    const frames = kind === 'frames';
    this.root.dataset.kind = kind;
    this.year.hidden = !frames;
    this.range.max = String(frames ? MONTHS - 1 : this.dates.length - 1);
    this.range.disabled = !frames && this.dates.length < 2;
    this.range.setAttribute('aria-label', frames ? 'Month' : 'Date');
    this.root.querySelectorAll('.tb-step').forEach((b, k) => b.setAttribute('aria-label', frames ? (k ? 'Next month' : 'Previous month') : (k ? 'Next day' : 'Previous day')));
    this.note.textContent = frames ? '1991–2020 monthly means, ERA5' : 'ERA5, about 6 days behind real time';
    this.render();
  }

  /** Move to a date or frame from outside (URL, tour) without firing the callbacks. */
  set(date: string, frame: Frame): void {
    this.index = Math.max(0, this.dates.indexOf(date));
    this.frame = frame;
    this.render();
  }

  private render(): void {
    const frames = this.kind === 'frames';
    const isYear = frames && this.frame === 'year';
    this.range.value = String(frames ? (isYear ? MONTHS - 1 : Number(this.frame) - 1) : this.index);
    this.range.classList.toggle('inactive', isYear);
    this.year.setAttribute('aria-pressed', String(isYear));
    const text = frames ? frameName(this.frame) : this.date;
    this.range.setAttribute('aria-valuetext', text);
    this.label.textContent = text;
  }

  private async go(i: number): Promise<void> {
    if (this.kind === 'frames') return this.goFrame(FRAMES[i]!);
    if (i === this.index) return;
    this.index = i;
    this.render();
    await this.onChange(this.date);
  }

  private async goFrame(f: Frame): Promise<void> {
    if (f === this.frame) return;
    this.frame = f;
    this.render();
    await this.onFrame(f);
  }

  step(delta: number): void {
    this.pause();
    if (this.kind === 'frames') void this.goFrame(stepFrame(this.frame, delta));
    else void this.go(stepIndex(this.index, delta, this.dates.length));
  }

  private async start(): Promise<void> {
    if (this.kind === 'frames') return this.startFrames();
    if (this.dates.length < 2) return;
    this.playing = true;
    this.play.textContent = '❚❚';
    this.play.setAttribute('aria-label', 'Pause');
    if (this.index === this.dates.length - 1) await this.go(0);
    while (this.playing && this.index < this.dates.length - 1) {
      const shown = Date.now();
      await new Promise((r) => setTimeout(r, PLAY_INTERVAL_MS));
      if (!this.playing) return;
      await this.go(this.index + 1); // waits until the next date is drawn
      if (Date.now() - shown > 10 * PLAY_INTERVAL_MS) break; // too slow to animate
    }
    this.pause();
  }

  /** The seasonal cycle is cyclic, so play loops until paused. */
  private async startFrames(): Promise<void> {
    this.playing = true;
    this.play.textContent = '❚❚';
    this.play.setAttribute('aria-label', 'Pause');
    while (this.playing && this.kind === 'frames') {
      const shown = Date.now();
      await new Promise((r) => setTimeout(r, PLAY_INTERVAL_MS));
      if (!this.playing || this.kind !== 'frames') return;
      await this.goFrame(playFrame(this.frame));
      if (Date.now() - shown > 10 * PLAY_INTERVAL_MS) break;
    }
    this.pause();
  }

  pause(): void {
    this.playing = false;
    this.play.textContent = '▶';
    this.play.setAttribute('aria-label', 'Play');
  }
}
