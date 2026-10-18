import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import { Map as MapLibreMap, setWorkerUrl } from 'maplibre-gl';
// MapLibre looks for its worker next to its own module, which a bundled build doesn't have;
// importing the URL makes Vite emit the file in builds.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { baseStyle } from './basemap';
import { MASKED, decodeAll, scalarCodes } from './codes';
import { lutBytes } from './colormaps';
import { cellIndex } from './grid';
import { InfoPanel } from './info';
import { RasterLayer } from './layers/raster';
import { Legend } from './legend';
import { fieldUrl, loadManifest, type Manifest } from './manifest';
import { LayerMenu, menuGroups } from './menu';
import { decodePng } from './png';
import { displayScale } from './scale';
import { TimeBar, nearbyDates } from './timebar';

setWorkerUrl(workerUrl);

const DATA = import.meta.env.VITE_DATA_URL ?? '/data';
const DEFAULT_LAYER = 'net_toa';
const PREFETCH_DAYS = 3;
const CACHE_SIZE = 40; // decoded fields, about 1.3 MB each

function fail(message: string): void {
  const app = document.getElementById('app')!;
  app.innerHTML = '';
  const p = document.createElement('p');
  p.className = 'fatal';
  p.textContent = message;
  app.append(p);
}

// Minimal view parameters until URL state lands (milestone 13): ?center=lng,lat&zoom=z
function parseCenter(text: string | null): [number, number] | null {
  const parts = text?.split(',').map(Number);
  return parts?.length === 2 && parts.every(Number.isFinite) ? [parts[0]!, parts[1]!] : null;
}

interface LoadedField {
  width: number;
  height: number;
  rgb: Uint8Array;
  codes: Uint16Array;
}

class App {
  private readonly cache = new Map<string, Promise<LoadedField>>(); // insertion order = LRU
  private codes: Uint16Array | null = null;
  private layerId = '';
  private request = 0;

  constructor(
    private readonly manifest: Manifest,
    private date: string,
    private readonly raster: RasterLayer,
    private readonly legend: Legend,
    private readonly menu: LayerMenu,
  ) {}

  private load(date: string, layer: string): Promise<LoadedField> {
    const key = `${date}/${layer}`;
    let p = this.cache.get(key);
    if (p) {
      this.cache.delete(key); // refresh its place in the LRU order
    } else {
      p = fetch(fieldUrl(DATA, this.manifest, date, layer)).then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const png = await decodePng(await r.arrayBuffer());
        return { width: png.width, height: png.height, rgb: png.data, codes: scalarCodes(png) };
      });
      p.catch(() => this.cache.delete(key));
    }
    this.cache.set(key, p);
    while (this.cache.size > CACHE_SIZE) this.cache.delete(this.cache.keys().next().value!);
    return p;
  }

  private prefetch(layer: string): void {
    const i = this.manifest.dates.indexOf(this.date);
    for (const d of nearbyDates(this.manifest.dates, i, PREFETCH_DAYS)) {
      this.load(d, layer).catch(() => undefined);
    }
  }

  setDate(date: string): Promise<void> {
    this.date = date;
    return this.select(this.layerId || DEFAULT_LAYER);
  }

  async select(layer: string): Promise<void> {
    const meta = this.manifest.layers[layer];
    if (!meta) return;
    const request = ++this.request;
    const date = this.date;
    this.menu.setSelected(layer);
    let field: LoadedField;
    try {
      field = await this.load(date, layer);
    } catch (e) {
      if (request === this.request) {
        this.codes = null;
        this.layerId = layer;
        this.legend.showMessage(`No data for ${meta.title} on ${date} (${e instanceof Error ? e.message : e})`);
      }
      return;
    }
    if (request !== this.request) return; // a later selection won
    const scale = displayScale(meta, meta.display === 'auto' ? decodeAll(field.codes, meta.encode) : undefined);
    this.raster.setData({
      width: field.width, height: field.height, rgb: field.rgb, encode: meta.encode, scale,
      lut: lutBytes(meta.colour), hatchZero: meta.hatch_zero,
    });
    this.legend.show(meta, scale);
    this.codes = field.codes;
    this.layerId = layer;
    document.body.dataset.layer = layer;
    document.body.dataset.date = date;
    this.prefetch(layer);
  }

  hover(lng: number, lat: number): void {
    const meta = this.manifest.layers[this.layerId];
    const cell = cellIndex(lng, lat, this.manifest.grid);
    if (!meta || !this.codes || !cell) return this.legend.showValue(null);
    const code = this.codes[cell.j * this.manifest.grid.nlon + cell.i]!;
    this.legend.showValue(decodeAll(Uint16Array.of(code), meta.encode)[0]!, code === MASKED);
  }
}

async function start(): Promise<void> {
  if (!document.createElement('canvas').getContext('webgl2')) {
    fail('This map needs WebGL2, which your browser or device does not support.');
    return;
  }
  const manifest = await loadManifest(DATA);
  const params = new URLSearchParams(location.search);
  const date = params.get('date') ?? manifest.dates.at(-1);
  if (!date) {
    fail('No data has been published yet.');
    return;
  }
  const wanted = params.get('layer') ?? DEFAULT_LAYER;
  const first = manifest.built_layers.includes(wanted) ? wanted : (manifest.built_layers[0] ?? wanted);

  const map = new MapLibreMap({
    container: 'map',
    style: baseStyle(),
    center: parseCenter(params.get('center')) ?? [0.25, 20],
    zoom: Number(params.get('zoom') ?? 1.4),
    renderWorldCopies: true,
    attributionControl: false, // credits are in the footer
  });
  document.getElementById('credits')!.textContent =
    `${manifest.credits} Coastlines and borders: Natural Earth (public domain). Map rendering: MapLibre GL JS.`;

  const info = new InfoPanel(document.getElementById('info') as HTMLDialogElement);
  const raster = new RasterLayer('field');
  const legend = new Legend(document.getElementById('legend')!);
  // The menu and the app need each other; the menu calls the app through this late binding.
  const handlers: { select: (id: string) => void } = { select: () => undefined };
  const menu = new LayerMenu(
    document.getElementById('menu')!,
    menuGroups(manifest),
    (id) => handlers.select(id),
    (id, opener) => info.open(manifest.layers[id]!, manifest.credits, opener),
  );
  const app = new App(manifest, date, raster, legend, menu);
  handlers.select = (id) => void app.select(id);
  new TimeBar(document.getElementById('timebar')!, manifest.dates, date, (d) => app.setDate(d));

  const toggle = document.getElementById('menu-toggle')!;
  toggle.addEventListener('click', () => {
    const open = document.body.classList.toggle('menu-open');
    toggle.setAttribute('aria-expanded', String(open));
  });

  await new Promise((resolve) => map.once('load', resolve));
  map.addLayer(raster, 'coastline-halo');
  await app.select(first);
  map.on('mousemove', (e) => app.hover(e.lngLat.lng, e.lngLat.lat));
  map.on('mouseout', () => legend.showValue(null));
  document.body.dataset.ready = 'true';
}

start().catch((e: unknown) => fail(`Could not load the map: ${e instanceof Error ? e.message : String(e)}`));
