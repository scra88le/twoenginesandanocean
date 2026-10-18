// Layer menu: the 9 story groups, one radio button per layer (one raster at a time).
// Native radios give keyboard navigation: Tab into the group, arrow keys move and select.
import type { Manifest } from './manifest';

export interface MenuLayer {
  id: string;
  title: string;
  summary: string;
  enabled: boolean;
}

export interface MenuGroup {
  number: number;
  name: string;
  layers: MenuLayer[];
}

export function menuGroups(m: Manifest): MenuGroup[] {
  const groups = new Map<number, MenuGroup>();
  for (const [id, meta] of Object.entries(m.layers)) {
    const g = groups.get(meta.group) ?? { number: meta.group, name: meta.group_name, layers: [] };
    g.layers.push({ id, title: meta.title, summary: meta.info.summary, enabled: m.built_layers.includes(id) });
    groups.set(meta.group, g);
  }
  return [...groups.values()].sort((a, b) => a.number - b.number);
}

export class LayerMenu {
  private readonly radios = new Map<string, HTMLInputElement>();

  constructor(
    root: HTMLElement,
    groups: MenuGroup[],
    private readonly onSelect: (id: string) => void,
    onInfo: (id: string, opener: HTMLElement) => void,
  ) {
    root.innerHTML = '<h2 class="menu-heading">Layers</h2>';
    for (const g of groups) {
      const fs = document.createElement('fieldset');
      const legend = document.createElement('legend');
      legend.textContent = `${g.number} · ${g.name}`;
      fs.append(legend);
      for (const layer of g.layers) {
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
        fs.append(row);
        this.radios.set(layer.id, input);
      }
      root.append(fs);
    }
  }

  /** Mark a layer as selected without firing onSelect. */
  setSelected(id: string): void {
    const r = this.radios.get(id);
    if (r) r.checked = true;
  }
}
