// Layer menu: the story groups, one radio button per layer (one raster at a time).
// Native radios give keyboard navigation: Tab into the group, arrow keys move and select.
import type { Manifest } from './manifest';

export interface MenuLayer {
  id: string;
  title: string;
  summary: string;
  enabled: boolean;
  advanced: boolean; // shown under "More layers"
}

export interface MenuGroup {
  number: number;
  name: string;
  blurb: string; // one line under the group's name
  layers: MenuLayer[]; // in menu order: the plain layers, then the advanced ones
}

export function menuGroups(m: Manifest): MenuGroup[] {
  const groups = new Map<number, MenuGroup>();
  // `menu_order` from the manifest; manifests from before it keep their own order.
  const ordered = Object.entries(m.layers).sort(([, a], [, b]) => (a.menu_order ?? 0) - (b.menu_order ?? 0));
  for (const [id, meta] of ordered) {
    const g = groups.get(meta.group) ?? {
      number: meta.group, name: meta.group_name, blurb: m.groups?.[meta.group]?.blurb ?? '', layers: [],
    };
    g.layers.push({
      id, title: meta.title, summary: meta.info.summary, enabled: m.built_layers.includes(id), advanced: !!meta.advanced,
    });
    groups.set(meta.group, g);
  }
  // plain before advanced, keeping the order within each (a stable sort)
  for (const g of groups.values()) g.layers.sort((a, b) => Number(a.advanced) - Number(b.advanced));
  return [...groups.values()].sort((a, b) => a.number - b.number);
}

export class LayerMenu {
  private readonly radios = new Map<string, HTMLInputElement>();
  private readonly more = new Map<string, HTMLDetailsElement>(); // layer id -> its "More layers"

  constructor(
    root: HTMLElement,
    groups: MenuGroup[],
    private readonly onSelect: (id: string) => void,
    onInfo: (id: string, opener: HTMLElement) => void,
  ) {
    // "Done" is only shown on phones, where the menu is a bottom sheet.
    root.innerHTML = `
      <div class="menu-head">
        <h2 class="menu-heading">Layers</h2>
        <button type="button" class="menu-close">Done</button>
      </div>`;
    for (const g of groups) {
      const fs = document.createElement('fieldset');
      const legend = document.createElement('legend');
      legend.textContent = g.name;
      fs.append(legend);
      if (g.blurb) {
        const blurb = document.createElement('p');
        blurb.className = 'group-blurb';
        blurb.textContent = g.blurb;
        fs.append(blurb);
      }
      const plain = g.layers.filter((l) => !l.advanced);
      const advanced = g.layers.filter((l) => l.advanced);
      for (const layer of plain) fs.append(this.row(layer, onInfo));
      if (advanced.length) {
        const details = document.createElement('details');
        details.className = 'more-layers';
        const summary = document.createElement('summary');
        summary.textContent = 'More layers';
        details.append(summary);
        for (const layer of advanced) {
          details.append(this.row(layer, onInfo));
          this.more.set(layer.id, details);
        }
        fs.append(details);
      }
      root.append(fs);
    }
  }

  private row(layer: MenuLayer, onInfo: (id: string, opener: HTMLElement) => void): HTMLElement {
    const row = document.createElement('div');
    row.className = 'layer-item';
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'radio';
    input.name = 'layer';
    input.value = layer.id;
    input.disabled = !layer.enabled;
    input.addEventListener('change', () => input.checked && this.onSelect(layer.id));
    const text = document.createElement('span');
    text.className = 'layer-text';
    const title = document.createElement('span');
    title.className = 'layer-title';
    title.textContent = layer.title;
    const summary = document.createElement('span');
    summary.className = 'layer-summary';
    summary.textContent = layer.enabled ? layer.summary : `${layer.summary} Not available yet.`;
    text.append(title, summary);
    label.append(input, text);
    const info = document.createElement('button');
    info.type = 'button';
    info.className = 'info-button';
    info.textContent = 'i';
    info.setAttribute('aria-label', `About ${layer.title}`);
    info.addEventListener('click', () => onInfo(layer.id, info));
    row.append(label, info);
    this.radios.set(layer.id, input);
    return row;
  }

  /** Mark a layer as selected without firing onSelect. */
  setSelected(id: string): void {
    const r = this.radios.get(id);
    if (r) r.checked = true;
    const more = this.more.get(id);
    if (more) more.open = true; // the selected layer is never hidden

  }
}
