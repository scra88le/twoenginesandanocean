import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import { Map as MapLibreMap, setWorkerUrl } from 'maplibre-gl';
// MapLibre looks for its worker next to its own module, which a bundled build doesn't have;
// importing the URL makes Vite emit the file in builds.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { baseStyle } from './basemap';
import { MASKED, decodeAll, scalarCodes, vectorCodes } from './codes';
import { lutBytes } from './colormaps';
import { cellIndex } from './grid';
import { InfoPanel } from './info';
import { ParticleLayer } from './layers/particles';
import { RasterLayer } from './layers/raster';
import { Legend } from './legend';
import { fieldUrl, loadManifest, uvUrl, type Manifest } from './manifest';
import { LayerMenu, menuGroups } from './menu';
import { OverlayControls, type ParticleChoice } from './overlays';
import { decodePng, type DecodedPng } from './png';
import { displayScale } from './scale';
import { TimeBar, nearbyDates } from './timebar';
import { LEVEL_LABELS, describeWind, isWindLevel, windAt } from './wind';

setWorkerUrl(workerUrl);

const DATA = import.meta.env.VITE_DATA_URL ?? '/data';
const DEFAULT_LAYER = 'net_toa';
const PREFETCH_DAYS = 3;
const CACHE_SIZE = 48; // decoded PNGs, 0.8 MB (scalar) or 1 MB (wind) each

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

// Particles are on unless ?particles=off; ?particles=wind100 (or jet250) picks the level.
function parseParticles(text: string | null): ParticleChoice {
  if (text === 'off') return { on: false, level: 'wind10' };
  return { on: true, level: isWindLevel(text) ? text : 'wind10' };
}

interface WindCodes {
  level: ParticleChoice['level'];
  u: Uint16Array;
  v: Uint16Array;
}

class App {
  private readonly cache = new Map<string, Promise<DecodedPng>>(); // insertion order = LRU
  private codes: Uint16Array | null = null;
  private wind: WindCodes | null = null;
  private layerId = '';
  private request = 0;
  private windRequest = 0;

  constructor(
    private readonly manifest: Manifest,
    private date: string,
    private readonly raster: RasterLayer,
    private readonly particles: ParticleLayer,
    private readonly legend: Legend,
    private readonly menu: LayerMenu,
    private particleChoice: ParticleChoice,
  ) {}

  private load(url: string): Promise<DecodedPng> {
    let p = this.cache.get(url);
    if (p) {
      this.cache.delete(url); // refresh its place in the LRU order
    } else {
      p = fetch(url).then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return decodePng(await r.arrayBuffer());
      });
      p.catch(() => this.cache.delete(url));
    }
    this.cache.set(url, p);
    while (this.cache.size > CACHE_SIZE) this.cache.delete(this.cache.keys().next().value!);
    return p;
  }

  private prefetch(url: (date: string) => string): void {
    const i = this.manifest.dates.indexOf(this.date);
    for (const d of nearbyDates(this.manifest.dates, i, PREFETCH_DAYS)) {
      this.load(url(d)).catch(() => undefined);
    }
  }

  async setDate(date: string): Promise<void> {
    this.date = date;
    await Promise.all([this.select(this.layerId || DEFAULT_LAYER), this.updateParticles()]);
  }

  setParticles(choice: ParticleChoice): Promise<void> {
    this.particleChoice = choice;
    return this.updateParticles();
  }

  /** Load the wind for the current date and level into the particle layer, or switch it off. */
  async updateParticles(): Promise<void> {
    const request = ++this.windRequest;
    const { on, level } = this.particleChoice;
    const meta = this.manifest.layers[level];
    if (!on || !meta?.uv_encode || !this.manifest.built_layers.includes(level)) {
      this.wind = null;
      this.particles.setWind(null);
      this.legend.showWind(null);
      document.body.dataset.particles = 'off';
      return;
    }
    const date = this.date;
    let png: DecodedPng;
    try {
      png = await this.load(uvUrl(DATA, this.manifest, date, level));
    } catch {
      if (request !== this.windRequest) return;
      this.wind = null;
      this.particles.setWind(null);
      this.legend.showWind(`No ${LEVEL_LABELS[level]} wind for ${date}`);
      document.body.dataset.particles = 'missing';
      return;
    }
    if (request !== this.windRequest) return; // a later change won
    const speedHi = meta.display === 'auto' ? meta.encode.hi : meta.display[1];
    this.particles.setWind({ width: png.width, height: png.height, rgba: png.data, encode: meta.uv_encode, speedHi });
    this.wind = { level, ...vectorCodes(png) };
    this.legend.showWind(this.windCaption());
    document.body.dataset.particles = level;
    this.prefetch((d) => uvUrl(DATA, this.manifest, d, level));
  }

  private windCaption(): string {
    return this.wind ? `Particles: wind at ${LEVEL_LABELS[this.wind.level]} (daily mean)` : '';
  }

  async select(layer: string): Promise<void> {
    const meta = this.manifest.layers[layer];
    if (!meta) return;
    const request = ++this.request;
    const date = this.date;
    this.menu.setSelected(layer);
    let field: DecodedPng;
    try {
      field = await this.load(fieldUrl(DATA, this.manifest, date, layer));
    } catch (e) {
      if (request === this.request) {
        this.codes = null;
        this.layerId = layer;
        this.legend.showMessage(`No data for ${meta.title} on ${date} (${e instanceof Error ? e.message : e})`);
      }
      return;
    }
    if (request !== this.request) return; // a later selection won
    const codes = scalarCodes(field);
    const scale = displayScale(meta, meta.display === 'auto' ? decodeAll(codes, meta.encode) : undefined);
    this.raster.setData({
      width: field.width, height: field.height, rgb: field.data, encode: meta.encode, scale,
      lut: lutBytes(meta.colour), hatchZero: meta.hatch_zero,
    });
    this.legend.show(meta, scale);
    this.codes = codes;
    this.layerId = layer;
    document.body.dataset.layer = layer;
    document.body.dataset.date = date;
    this.prefetch((d) => fieldUrl(DATA, this.manifest, d, layer));
  }

  hover(lng: number, lat: number): void {
    this.hoverWind(lng, lat);
    const meta = this.manifest.layers[this.layerId];
    const cell = cellIndex(lng, lat, this.manifest.grid);
    if (!meta || !this.codes || !cell) return this.legend.showValue(null);
    const code = this.codes[cell.j * this.manifest.grid.nlon + cell.i]!;
    this.legend.showValue(decodeAll(Uint16Array.of(code), meta.encode)[0]!, code === MASKED);
  }

  private hoverWind(lng: number, lat: number): void {
    const enc = this.wind && this.manifest.layers[this.wind.level]?.uv_encode;
    if (!this.wind || !enc) return;
    const w = windAt(this.wind.u, this.wind.v, enc, this.manifest.grid, lng, lat);
    this.legend.showWind(w ? `Wind ${LEVEL_LABELS[this.wind.level]}: ${describeWind(w)}` : this.windCaption());
  }

  hoverEnd(): void {
    this.legend.showValue(null);
    if (this.wind) this.legend.showWind(this.windCaption());
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
    maxPitch: 0, // the raster and particle layers draw on a flat map
    attributionControl: false, // credits are in the footer
  });
  document.getElementById('credits')!.textContent =
    `${manifest.credits} Coastlines and borders: Natural Earth (public domain). Map rendering: MapLibre GL JS.`;

  const info = new InfoPanel(document.getElementById('info') as HTMLDialogElement);
  const raster = new RasterLayer('field');
  const particles = new ParticleLayer('particles');
  const legend = new Legend(document.getElementById('legend')!);
  // The menu and the app need each other; the menu calls the app through this late binding.
  const handlers: { select: (id: string) => void } = { select: () => undefined };
  const menu = new LayerMenu(
    document.getElementById('menu')!,
    menuGroups(manifest),
    (id) => handlers.select(id),
    (id, opener) => info.open(manifest.layers[id]!, manifest.credits, opener),
  );
  const choice = parseParticles(params.get('particles'));
  const app = new App(manifest, date, raster, particles, legend, menu, choice);
  handlers.select = (id) => void app.select(id);
  const overlays = new OverlayControls(manifest, choice, (c) => void app.setParticles(c));
  document.querySelector('#menu .menu-heading')!.after(overlays.element);
  void app.setParticles(overlays.choice);
  new TimeBar(document.getElementById('timebar')!, manifest.dates, date, (d) => app.setDate(d));

  const toggle = document.getElementById('menu-toggle')!;
  toggle.addEventListener('click', () => {
    const open = document.body.classList.toggle('menu-open');
    toggle.setAttribute('aria-expanded', String(open));
  });

  // ?debug exposes the map and particle layer to the console and the Playwright tests.
  if (params.has('debug')) Object.assign(window, { ehe: { map, particles } });

  await new Promise((resolve) => map.once('load', resolve));
  map.addLayer(raster, 'coastline-halo');
  map.addLayer(particles); // on top, over the coastlines
  await app.select(first);
  map.on('mousemove', (e) => app.hover(e.lngLat.lng, e.lngLat.lat));
  map.on('mouseout', () => app.hoverEnd());
  document.body.dataset.ready = 'true';
}

start().catch((e: unknown) => fail(`Could not load the map: ${e instanceof Error ? e.message : String(e)}`));
