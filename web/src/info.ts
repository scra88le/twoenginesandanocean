// Info panel: where a layer comes from, how it is computed, and what it means.
import { prettyUnits } from './format';
import type { LayerMeta } from './manifest';

export interface InfoSection {
  label: string;
  text: string;
}

/** The first clause of a mask explanation, for the legend and hover text. */
export const maskLabel = (text: string) => text.split(/[:.](?:\s|$)/)[0]!.trim();

export function infoSections(meta: LayerMeta, credits: string): InfoSection[] {
  const i = meta.info;
  const sections: InfoSection[] = [
    { label: 'Source', text: i.source },
    { label: 'Units', text: prettyUnits(meta.units) },
    { label: 'Sign convention', text: i.sign },
    { label: 'Formula', text: i.formula },
    { label: 'What it means for the heat engine', text: i.meaning },
    { label: 'Caveats', text: i.caveats },
  ];
  if (i.mask) sections.push({ label: 'Grey cells', text: i.mask });
  sections.push({ label: 'Data credit', text: credits });
  return sections;
}

export class InfoPanel {
  private opener: HTMLElement | null = null;

  constructor(private readonly dialog: HTMLDialogElement) {
    dialog.addEventListener('close', () => this.opener?.focus());
    dialog.addEventListener('click', (e) => e.target === dialog && dialog.close()); // backdrop
  }

  open(meta: LayerMeta, credits: string, opener: HTMLElement): void {
    this.opener = opener;
    const d = this.dialog;
    d.innerHTML = '';
    d.setAttribute('aria-labelledby', 'info-title');
    const head = document.createElement('div');
    head.className = 'info-head';
    const h = document.createElement('h2');
    h.id = 'info-title';
    h.textContent = meta.title;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'info-close';
    close.textContent = 'Close';
    close.addEventListener('click', () => d.close());
    head.append(h, close);
    const summary = document.createElement('p');
    summary.className = 'info-summary';
    summary.textContent = meta.info.summary;
    const dl = document.createElement('dl');
    for (const s of infoSections(meta, credits)) {
      const dt = document.createElement('dt');
      dt.textContent = s.label;
      const dd = document.createElement('dd');
      dd.textContent = s.text;
      dl.append(dt, dd);
    }
    d.append(head, summary, dl);
    d.showModal();
    close.focus();
  }
}
