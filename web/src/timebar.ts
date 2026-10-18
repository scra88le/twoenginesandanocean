// Time bar: the last 90 available days, newest on the right, with play / pause / step.

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

export class TimeBar {
  private index: number;
  private playing = false;
  private readonly range: HTMLInputElement;
  private readonly label: HTMLElement;
  private readonly play: HTMLButtonElement;

  constructor(
    root: HTMLElement,
    private readonly dates: string[],
    initial: string,
    private readonly onChange: (date: string) => Promise<void>,
  ) {
    this.index = Math.max(0, dates.indexOf(initial));
    root.innerHTML = `
      <button type="button" class="tb-step" data-step="-1" aria-label="Previous day">‹</button>
      <button type="button" class="tb-play" aria-label="Play">▶</button>
      <button type="button" class="tb-step" data-step="1" aria-label="Next day">›</button>
      <input type="range" class="tb-range" min="0" step="1" aria-label="Date" />
      <div class="tb-text"><span class="tb-date" aria-live="polite"></span>
        <span class="tb-note">ERA5, about 6 days behind real time</span></div>`;
    this.range = root.querySelector('.tb-range')!;
    this.label = root.querySelector('.tb-date')!;
    this.play = root.querySelector('.tb-play')!;
    this.range.max = String(dates.length - 1);
    this.range.disabled = dates.length < 2;
    for (const b of root.querySelectorAll<HTMLButtonElement>('.tb-step')) {
      b.addEventListener('click', () => this.step(Number(b.dataset.step)));
    }
    this.play.addEventListener('click', () => (this.playing ? this.pause() : void this.start()));
    this.range.addEventListener('input', () => void this.go(Number(this.range.value)));
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      // Arrow keys belong to whatever has focus: the menu, the slider, the map canvas.
      const t = e.target as HTMLElement;
      if (t !== document.body && !t.matches('.tb-step, .tb-play')) return;
      e.preventDefault();
      this.step(e.key === 'ArrowLeft' ? -1 : 1);
    });
    this.render();
  }

  get date(): string {
    return this.dates[this.index]!;
  }

  private render(): void {
    this.range.value = String(this.index);
    this.range.setAttribute('aria-valuetext', this.date);
    this.label.textContent = this.date;
  }

  private async go(i: number): Promise<void> {
    if (i === this.index) return;
    this.index = i;
    this.render();
    await this.onChange(this.date);
  }

  step(delta: number): void {
    this.pause();
    void this.go(stepIndex(this.index, delta, this.dates.length));
  }

  private async start(): Promise<void> {
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

  pause(): void {
    this.playing = false;
    this.play.textContent = '▶';
    this.play.setAttribute('aria-label', 'Play');
  }
}
