// The guided tour: a card with Back / Next, a progress row, and the story step it shows.
// The card only presents a step; what a step does to the map (layer, overlays, view) is the
// callback's job, so the app stays the one place that changes the map.
import { renderBody, type StoryStep } from './story';

export class Tour {
  private index = -1;

  private readonly title: HTMLElement;
  private readonly count: HTMLElement;
  private readonly body: HTMLElement;
  private readonly back: HTMLButtonElement;
  private readonly next: HTMLButtonElement;
  private readonly dots: HTMLButtonElement[] = [];

  constructor(
    private readonly root: HTMLElement,
    private readonly steps: StoryStep[],
    private readonly onStep: (step: StoryStep, index: number) => void,
    private readonly onClose: () => void,
  ) {
    root.innerHTML = `
      <div class="tour-head">
        <div class="tour-count"></div>
        <button type="button" class="tour-close" aria-label="Close the tour">×</button>
      </div>
      <h2 class="tour-title"></h2>
      <div class="tour-body" aria-live="polite"></div>
      <div class="tour-dots" role="group" aria-label="Steps"></div>
      <div class="tour-nav">
        <button type="button" class="tour-back">Back</button>
        <button type="button" class="tour-next">Next</button>
      </div>`;
    this.title = root.querySelector('.tour-title')!;
    this.count = root.querySelector('.tour-count')!;
    this.body = root.querySelector('.tour-body')!;
    this.back = root.querySelector('.tour-back')!;
    this.next = root.querySelector('.tour-next')!;
    const dots = root.querySelector('.tour-dots')!;
    steps.forEach((s, i) => {
      const d = document.createElement('button');
      d.type = 'button';
      d.className = 'tour-dot';
      d.setAttribute('aria-label', `Step ${i + 1}: ${s.title}`);
      d.addEventListener('click', () => this.go(i));
      dots.append(d);
      this.dots.push(d);
    });
    this.back.addEventListener('click', () => this.go(this.index - 1));
    this.next.addEventListener('click', () => (this.index === steps.length - 1 ? this.close() : this.go(this.index + 1)));
    root.querySelector('.tour-close')!.addEventListener('click', () => this.close());
    root.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft') this.go(this.index - 1);
      else if (e.key === 'ArrowRight') this.go(this.index + 1);
      else return;
      e.preventDefault();
    });
    document.addEventListener('keydown', (e) => {
      // Escape closes the tour, unless something modal (the info panel) is on top of it.
      if (e.key === 'Escape' && this.isOpen && !document.querySelector('dialog[open]')) this.close();
    });
  }

  get isOpen(): boolean {
    return !this.root.hidden;
  }

  get current(): number {
    return this.index;
  }

  /** Open the tour at a step (0-based). */
  start(index = 0): void {
    this.root.hidden = false;
    document.body.classList.add('tour-active');
    this.go(index);
    this.next.focus();
  }

  go(index: number): void {
    if (index < 0 || index >= this.steps.length) return;
    this.index = index;
    const step = this.steps[index]!;
    this.count.textContent = `Step ${index + 1} of ${this.steps.length}`;
    this.title.textContent = step.title;
    this.body.replaceChildren(...renderBody(step.body));
    this.back.disabled = index === 0;
    this.next.textContent = index === this.steps.length - 1 ? 'Finish' : 'Next';
    this.dots.forEach((d, i) => {
      d.classList.toggle('current', i === index);
      d.setAttribute('aria-current', i === index ? 'step' : 'false');
    });
    document.body.dataset.tour = String(index + 1);
    document.body.dataset.tourStep = step.id;
    this.onStep(step, index);
    this.publishHeight();
  }

  close(): void {
    if (!this.isOpen) return;
    this.root.hidden = true;
    this.index = -1;
    document.body.classList.remove('tour-active');
    delete document.body.dataset.tour;
    delete document.body.dataset.tourStep;
    document.documentElement.style.removeProperty('--tour-h');
    this.onClose();
  }

  /** Tell the CSS how tall the card is, so the readout can sit below it. */
  private publishHeight(): void {
    document.documentElement.style.setProperty('--tour-h', `${this.root.offsetHeight}px`);
  }
}
