import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import { Map as MapLibreMap, Marker, setWorkerUrl } from 'maplibre-gl';
// MapLibre looks for its worker next to its own module, which a bundled build doesn't have;
// importing the URL makes Vite emit the file in builds.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { anomalyNote, anomalyView } from './anomaly';
import { baseStyle } from './basemap';
import { parseSeries, pointCodes, seriesCodes, tileOf } from './chunks';
import { MASKED, decodeAll, scalarCodes, vectorCodes } from './codes';
import { lutBytes } from './colormaps';
import { formatValue } from './format';
import { cellIndex } from './grid';
import { InfoPanel } from './info';
import { ArrowLayer, arrowReference } from './layers/arrows';
import { ParticleLayer } from './layers/particles';
import { RasterLayer } from './layers/raster';
import { Legend } from './legend';
import { anomalyUrl, fieldUrl, hasAnomaly, loadManifest, tileUrl, uvUrl, type LayerMeta, type Manifest } from './manifest';
import { LayerMenu, menuGroups } from './menu';
import { AnomalySwitch, ArrowsSwitch, OverlayControls, type ParticleChoice } from './overlays';
import { decodePng, type DecodedPng } from './png';
import { ReadoutPanel, climAtCell, readoutItems } from './readout';
import { displayScale } from './scale';
import { parseCards, type StoryStep, type StoryView } from './story';
import { TimeBar, nearbyDates } from './timebar';
import { Tour } from './tour';
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

interface Pin {
  lng: number; // cell centre
  lat: number;
  tx: number;
  ty: number;
  k: number; // index within the tile
}

interface WindCodes {
  level: ParticleChoice['level'];
  u: Uint16Array;
  v: Uint16Array;
}

class App {
  private readonly cache = new Map<string, Promise<DecodedPng>>(); // insertion order = LRU
  private readonly chunks = new Map<string, Promise<ArrayBuffer>>(); // point and series chunks
  private pinned: Pin | null = null;
  private view: LayerMeta | null = null; // the active layer as drawn: itself or its anomaly
  private anomalyOn = false;
  anomalySwitch: AnomalySwitch | null = null;
  private marker: Marker | null = null;
  private pinRequest = 0;
  private arrowsOn = false;
  private arrowRequest = 0;
  private chartRequest = 0;
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
    private readonly readout: ReadoutPanel,
    private readonly map: MapLibreMap,
    private readonly arrows: ArrowLayer,
  ) {}

  private loadChunk(url: string): Promise<ArrayBuffer> {
    let p = this.chunks.get(url);
    if (p) {
      this.chunks.delete(url);
    } else {
      p = fetch(url).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.arrayBuffer();
      });
      p.catch(() => this.chunks.delete(url));
    }
    this.chunks.set(url, p);
    while (this.chunks.size > CACHE_SIZE) this.chunks.delete(this.chunks.keys().next().value!);
    return p;
  }

  /** Open the readout for the cell under a point, or move it there. */
  pin(lng: number, lat: number): void {
    const g = this.manifest.grid;
    const cell = cellIndex(lng, lat, g);
    if (!cell) return;
    const centre = { lng: g.lon0 + cell.i * g.step, lat: g.lat0 - cell.j * g.step };
    this.pinned = { ...centre, ...tileOf(cell, this.manifest.points?.tile ?? 20) };
    const el = document.createElement('div');
    el.className = 'pin';
    this.marker?.remove();
    // Keep the marker on the world copy that was clicked.
    const copy = 360 * Math.round((lng - centre.lng) / 360);
    this.marker = new Marker({ element: el }).setLngLat([centre.lng + copy, centre.lat]).addTo(this.map);
    this.readout.open();
    void this.updateReadout();
    void this.updateChart();
  }

  unpin(): void {
    this.pinned = null;
    this.marker?.remove();
    this.marker = null;
    this.readout.close();
    delete document.body.dataset.readout;
  }

  private async updateReadout(): Promise<void> {
    const pin = this.pinned;
    const points = this.manifest.points;
    if (!pin) return;
    const request = ++this.pinRequest;
    const date = this.date;
    this.readout.showPlace(pin.lng, pin.lat, date);
    if (!points) {
      this.readout.showTable('Point data has not been published yet.');
      return;
    }
    let codes: Map<string, number>;
    try {
      const buf = await this.loadChunk(tileUrl(DATA, points.file, { date, tx: pin.tx, ty: pin.ty }));
      codes = pointCodes(buf, points.fields, points.tile, pin.k);
    } catch {
      if (request === this.pinRequest) this.readout.showTable(`No point data for ${date}.`);
      return;
    }
    if (request !== this.pinRequest) return;
    this.readout.showTable(readoutItems(this.manifest, codes));
    document.body.dataset.readout = `${pin.tx}_${pin.ty}_${pin.k}@${date}`;
  }

  private async updateChart(): Promise<void> {
    const pin = this.pinned;
    const meta = this.manifest.layers[this.layerId];
    const series = this.manifest.series;
    const tile = this.manifest.points?.tile ?? 20;
    if (!pin || !meta) return;
    const request = ++this.chartRequest;
    if (!series) {
      this.readout.showChartMessage('The 90-day series has not been published yet.');
      return;
    }
    const layer = this.layerId;
    let s: ReturnType<typeof parseSeries>;
    try {
      s = parseSeries(await this.loadChunk(tileUrl(DATA, series.file, { layer, tx: pin.tx, ty: pin.ty })), tile);
    } catch {
      if (request === this.chartRequest) this.readout.showChartMessage(`No 90-day series for ${meta.title} yet.`);
      return;
    }
    const clim = await this.climatologyAt(layer, pin, tile);
    if (request !== this.chartRequest) return;
    this.readout.showChart(meta, s.dates, seriesCodes(s, tile, pin.k), this.date, clim);
    document.body.dataset.chart = `${layer}:${s.dates.length}${typeof clim === 'string' ? '' : ':clim'}`;
  }

  /** The layer's monthly means at the pinned cell, or why there are none. */
  private async climatologyAt(layer: string, pin: Pin, tile: number) {
    const clim = this.manifest.clim;
    const meta = this.manifest.layers[layer]!;
    if (!clim) return 'Climatology line: not published yet.';
    if (!clim.layers.includes(layer)) return 'No climatology for this layer (see its info).';
    try {
      const buf = await this.loadChunk(tileUrl(DATA, clim.series, { layer, tx: pin.tx, ty: pin.ty }));
      return { byMonth: climAtCell(buf, tile, pin.k, meta.encode), period: clim.period };
    } catch {
      return 'Climatology line: no data for this place.';
    }
  }

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
    await Promise.all([
      this.select(this.layerId || DEFAULT_LAYER),
      this.updateParticles(),
      this.updateArrows(),
      this.updateReadout(),
    ]);
  }

  /** Set the transport arrows on or off and (re)load their field. */
  setArrows(on: boolean): Promise<void> {
    this.arrowsOn = on;
    return this.updateArrows();
  }

  setArrowsFlag(on: boolean): void {
    this.arrowsOn = on;
  }

  async updateArrows(): Promise<void> {
    const request = ++this.arrowRequest;
    const meta = this.manifest.layers.flux_e;
    const built = this.manifest.built_layers.includes('flux_e');
    if (!this.arrowsOn || !meta?.uv_encode || !built) {
      this.arrows.setField(null);
      this.legend.showArrows(null);
      document.body.dataset.arrows = 'off';
      return;
    }
    const date = this.date;
    let png: DecodedPng;
    try {
      png = await this.load(uvUrl(DATA, this.manifest, date, 'flux_e'));
    } catch {
      if (request !== this.arrowRequest) return;
      this.arrows.setField(null);
      this.legend.showArrows(`No transport arrows for ${date}`);
      document.body.dataset.arrows = 'missing';
      return;
    }
    if (request !== this.arrowRequest) return;
    const { u, v } = vectorCodes(png);
    const reference = arrowReference(u, v, meta.uv_encode);
    this.arrows.setField({ u, v, encode: meta.uv_encode, grid: this.manifest.grid, reference });
    this.legend.showArrows(
      `Arrows: divergent energy transport; full length is ${formatValue(reference, meta.units, meta.encode)}`,
    );
    document.body.dataset.arrows = 'on';
    this.prefetch((d) => uvUrl(DATA, this.manifest, d, 'flux_e'));
  }

  /**
   * Show a story step: its layer with the anomaly off, its overlays, and fly to its view.
   * (A step's overlays are exactly what it lists: anything not listed is switched off.)
   */
  async showStep(step: StoryStep, level: ParticleChoice['level']): Promise<void> {
    this.anomalyOn = false;
    this.particleChoice = { on: step.particles !== null, level: step.particles ?? level };
    this.arrowsOn = step.arrows;
    this.flyTo(step.view);
    await Promise.all([this.select(step.layer), this.updateParticles(), this.updateArrows()]);
  }

  /** Move the map; reduced-motion users get a jump, as MapLibre does for non-essential moves. */
  flyTo(view: StoryView): void {
    this.map.flyTo({ center: [view.lng, view.lat], zoom: view.zoom, duration: 1800, essential: false });
  }

  /** Set the mode before the first draw, without drawing. */
  setAnomalyFlag(on: boolean): void {
    this.anomalyOn = on;
  }

  setAnomaly(on: boolean): Promise<void> {
    this.anomalyOn = on;
    return this.select(this.layerId || DEFAULT_LAYER);
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
    const anom = this.anomalyOn && hasAnomaly(this.manifest, layer);
    const view = anom ? anomalyView(meta) : meta;
    const url = (d: string) => (anom ? anomalyUrl : fieldUrl)(DATA, this.manifest, d, layer);
    let field: DecodedPng;
    try {
      field = await this.load(url(date));
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
    const scale = displayScale(view, view.display === 'auto' ? decodeAll(codes, view.encode) : undefined);
    this.raster.setData({
      width: field.width, height: field.height, rgb: field.data, encode: view.encode, scale,
      lut: lutBytes(view.colour), hatchZero: view.hatch_zero,
    });
    const notes = anom
      ? [anomalyNote(this.manifest.clim!.period, date)]
      : this.anomalyOn ? ['No anomaly for this layer (see its info): showing the value'] : [];
    this.legend.show(view, scale, notes, anom);
    this.codes = codes;
    this.view = view;
    this.layerId = layer;
    this.anomalySwitch?.setLayerHasAnomaly(hasAnomaly(this.manifest, layer));
    document.body.dataset.layer = layer;
    document.body.dataset.date = date;
    document.body.dataset.anomaly = anom ? 'on' : this.anomalyOn ? 'unavailable' : 'off';
    this.prefetch(url);
    void this.updateChart(); // the chart follows the active layer and marks the date
  }

  hover(lng: number, lat: number): void {
    this.hoverWind(lng, lat);
    const meta = this.view;
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
  const closers: { close: () => void } = { close: () => undefined };
  const readout = new ReadoutPanel(document.getElementById('readout')!, () => closers.close());
  const arrows = new ArrowLayer('arrows');
  const app = new App(manifest, date, raster, particles, legend, menu, choice, readout, map, arrows);
  closers.close = () => app.unpin();
  handlers.select = (id) => void app.select(id);
  const overlays = new OverlayControls(manifest, choice, (c) => void app.setParticles(c));
  document.querySelector('#menu .menu-heading')!.after(overlays.element);
  // ?anom=1 starts in anomaly mode (temporary, until URL state lands in milestone 13).
  const anomaly = new AnomalySwitch(manifest, params.get('anom') === '1', (on) => void app.setAnomaly(on));
  // ?arrows=1 starts with the transport arrows on (temporary, like ?anom).
  const arrowSwitch = new ArrowsSwitch(manifest, params.get('arrows') === '1', (on) => void app.setArrows(on));
  overlays.element.append(arrowSwitch.element, anomaly.element);
  app.anomalySwitch = anomaly;
  if (anomaly.on) app.setAnomalyFlag(true);
  if (arrowSwitch.on) app.setArrowsFlag(true);
  void app.setParticles(overlays.choice);

  // The guided tour: cards from story/*.md, each setting a layer, overlays and view.
  const steps = parseCards(
    import.meta.glob('../../story/*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
  );
  const tour = new Tour(
    document.getElementById('tour')!,
    steps,
    (step) => {
      overlays.set({ on: step.particles !== null, level: step.particles ?? overlays.choice.level });
      arrowSwitch.set(step.arrows);
      anomaly.set(false);
      void app.showStep(step, overlays.choice.level);
    },
    () => undefined, // closing keeps the map as the last step left it
  );
  const tourButton = document.createElement('button');
  tourButton.type = 'button';
  tourButton.className = 'tour-start';
  tourButton.textContent = 'Take the tour';
  tourButton.addEventListener('click', () => {
    document.body.classList.remove('menu-open'); // on phones the menu would cover the card
    document.getElementById('menu-toggle')?.setAttribute('aria-expanded', 'false');
    tour.start(0);
  });
  document.querySelector('#menu .menu-heading')!.after(tourButton);
  new TimeBar(document.getElementById('timebar')!, manifest.dates, date, (d) => app.setDate(d));

  const toggle = document.getElementById('menu-toggle')!;
  toggle.addEventListener('click', () => {
    const open = document.body.classList.toggle('menu-open');
    toggle.setAttribute('aria-expanded', String(open));
  });

  // ?debug exposes the map and particle layer to the console and the Playwright tests.
  if (params.has('debug')) Object.assign(window, { ehe: { map, particles, arrows } });

  await new Promise((resolve) => map.once('load', resolve));
  map.addLayer(raster, 'coastline-halo');
  map.addLayer(arrows); // under the particles, over the coastlines
  map.addLayer(particles);
  await app.select(first);
  void app.updateArrows();
  map.on('mousemove', (e) => app.hover(e.lngLat.lng, e.lngLat.lat));
  map.on('mouseout', () => app.hoverEnd());
  map.on('click', (e) => app.pin(e.lngLat.lng, e.lngLat.lat));
  // Temporary until URL state (milestone 13): ?pin=lng,lat opens the readout there.
  const pin = parseCenter(params.get('pin'));
  if (pin) app.pin(pin[0], pin[1]);
  document.body.dataset.ready = 'true';
  // ?tour=N opens the tour at step N (1-based), for links and tests.
  const tourStep = Number(params.get('tour'));
  if (Number.isInteger(tourStep) && tourStep >= 1 && tourStep <= steps.length) tour.start(tourStep - 1);
}

start().catch((e: unknown) => fail(`Could not load the map: ${e instanceof Error ? e.message : String(e)}`));
