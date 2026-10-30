import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import { Map as MapLibreMap, Marker, setWorkerUrl } from 'maplibre-gl';
// MapLibre looks for its worker next to its own module, which a bundled build doesn't have;
// importing the URL makes Vite emit the file in builds.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { anomalyView } from './anomaly';
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
import { anomalyUrl, climUrl, climUvUrl, fieldUrl, loadManifest, tileUrl, uvUrl, type LayerMeta, type Manifest } from './manifest';
import { LayerMenu, menuGroups } from './menu';
import { FRAMES, frameName, meanFlowText, resolveMode, availableModes, switchNote, timescaleText, type Frame, type Mode } from './modes';
import { ArrowsSwitch, ModeSwitch, OverlayControls, type ParticleChoice } from './overlays';
import { decodePng, type DecodedPng } from './png';
import { EngineStrip } from './enginestrip';
import { ZonalPanel } from './zonalpanel';
import { loadZonal, zonalUrl } from './zonal';
import { ReadoutPanel, climAtCell, readoutItems } from './readout';
import { displayScale } from './scale';
import { parseCards, type StoryStep, type StoryView } from './story';
import { TimeBar, nearbyDates } from './timebar';
import { Tour } from './tour';
import { DEFAULT_LAYER, readState, stateQuery, wrapLng, type ViewState } from './urlstate';
import { LEVEL_LABELS, describeWind, windAt } from './wind';

setWorkerUrl(workerUrl);

const DATA = import.meta.env.VITE_DATA_URL ?? '/data';
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

interface Pin {
  lng: number; // cell centre
  lat: number;
  tx: number;
  ty: number;
  k: number; // index within the tile
}

interface WindCodes {
  level: ParticleChoice['level'];
  mean: boolean; // the 1991–2020 mean flow of a climate frame, not a day
  u: Uint16Array;
  v: Uint16Array;
}

class App {
  private readonly cache = new Map<string, Promise<DecodedPng>>(); // insertion order = LRU
  private readonly chunks = new Map<string, Promise<ArrayBuffer>>(); // point and series chunks
  private pinned: Pin | null = null;
  private view: LayerMeta | null = null; // the active layer as drawn: itself or its anomaly
  private mode: Mode = 'today';
  private frame: Frame = 'year';
  modeSwitch: ModeSwitch | null = null;
  timebar: TimeBar | null = null;
  private marker: Marker | null = null;
  private pinRequest = 0;
  private arrowsOn = false;
  private arrowRequest = 0;
  private zonalRequest = 0;
  /** Called after anything the URL records changes; main.ts writes the address bar. */
  onStateChange: (() => void) | null = null;
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
    private readonly zonal: ZonalPanel,
    private readonly strip: EngineStrip,
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

  /** What the visitor is looking at, as the URL records it. */
  state(): ViewState {
    const c = this.map.getCenter();
    return {
      layer: this.layerId || DEFAULT_LAYER,
      date: this.date,
      mode: this.mode,
      frame: this.frame,
      particles: this.particleChoice,
      arrows: this.arrowsOn,
      panel: this.zonal.isOpen,
      center: [wrapLng(c.lng), c.lat],
      zoom: this.map.getZoom(),
      pin: this.pinned ? [this.pinned.lng, this.pinned.lat] : null,
    };
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
    this.onStateChange?.();
  }

  unpin(): void {
    this.pinned = null;
    this.marker?.remove();
    this.marker = null;
    this.readout.close();
    delete document.body.dataset.readout;
    this.onStateChange?.();
  }

  private async updateReadout(): Promise<void> {
    const pin = this.pinned;
    const points = this.manifest.points;
    if (!pin) return;
    const request = ++this.pinRequest;
    const date = this.date;
    const clim = this.manifest.clim;
    const climate = this.mode === 'climate' && !!clim?.points;
    const when = climate ? `${frameName(this.frame)}, ${clim!.period.replace('-', '–')}` : date;
    this.readout.showPlace(pin.lng, pin.lat, when);
    if (climate) {
      try {
        const buf = await this.loadChunk(tileUrl(DATA, clim!.points!, { frame: this.frame, tx: pin.tx, ty: pin.ty }));
        const codes = pointCodes(buf, points!.fields, points!.tile, pin.k);
        if (request !== this.pinRequest) return;
        this.readout.showTable(readoutItems(this.manifest, codes));
        document.body.dataset.readout = `${pin.tx}_${pin.ty}_${pin.k}@${this.frame}`;
      } catch {
        if (request === this.pinRequest) this.readout.showTable(`No climate point data for ${when}.`);
      }
      return;
    }
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
    if (this.mode === 'climate' && this.manifest.clim) {
      const clim = await this.climatologyAt(this.layerId, pin, tile);
      if (request !== this.chartRequest) return;
      if (typeof clim === 'string') this.readout.showChartMessage(clim);
      else {
        const month = this.frame === 'year' ? null : Number(this.frame);
        this.readout.showClimateChart(meta, clim.byMonth, month, clim.period);
        document.body.dataset.chart = `${this.layerId}:climate`;
      }
      return;
    }
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

  /** Pre-fetch all frames of a climate file (null where none is published). */
  private prefetchFrames(url: (frame: string) => string | null): void {
    for (const f of FRAMES) {
      const u = url(f);
      if (u) this.load(u).catch(() => undefined);
    }
  }

  private prefetch(url: (date: string) => string): void {
    const i = this.manifest.dates.indexOf(this.date);
    for (const d of nearbyDates(this.manifest.dates, i, PREFETCH_DAYS)) {
      this.load(url(d)).catch(() => undefined);
    }
  }

  /** Load the zonal file of what is on screen (Climate frame, or Today's date) for the strip and, if open, the panel. */
  async updateZonal(): Promise<void> {
    const request = ++this.zonalRequest;
    const { mode, frame, date } = this;
    const url = zonalUrl(DATA, this.manifest, mode, frame, date);
    const z = url ? await loadZonal(url) : null;
    if (request !== this.zonalRequest) return;
    const period = (this.manifest.clim?.period ?? '1991-2020').replace('-', '–');
    const what = mode === 'climate' ? `${period} ${meanFlowText(frame)}` : date;
    const shown = mode === 'climate' ? frame : null; // a daily date has no frame
    this.strip.update(z, shown, what);
    if (!this.zonal.isOpen) return;
    this.zonal.show(
      z, shown, what,
      mode === 'climate' ? 'ERA5 monthly means, zonal means over all longitudes.' : 'ERA5 daily means, zonal means over all longitudes.',
    );
  }

  /** Open or close the zonal budget panel. */
  setPanel(open: boolean): Promise<void> {
    if (open) this.zonal.open();
    else this.zonal.close();
    this.onStateChange?.();
    return this.updateZonal();
  }

  async setDate(date: string): Promise<void> {
    this.date = date;
    this.onStateChange?.();
    await Promise.all([
      this.select(this.layerId || DEFAULT_LAYER),
      this.updateParticles(),
      this.updateArrows(),
      this.updateReadout(),
      this.updateZonal(),
    ]);
  }

  /** Set the transport arrows on or off and (re)load their field. */
  setArrows(on: boolean): Promise<void> {
    this.arrowsOn = on;
    this.onStateChange?.();
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
    const climate = this.mode === 'climate';
    const clim = this.manifest.clim;
    const frame = this.frame;
    const date = this.date;
    const url = climate ? climUvUrl(DATA, clim, frame, 'flux_e') : uvUrl(DATA, this.manifest, date, 'flux_e');
    const when = climate ? frameName(frame) : date;
    let png: DecodedPng | null = null;
    if (url) {
      try {
        png = await this.load(url);
      } catch {
        png = null;
      }
    }
    if (request !== this.arrowRequest) return;
    if (!png) {
      this.arrows.setField(null);
      this.legend.showArrows(climate ? `No climate transport arrows for ${when}` : `No transport arrows for ${date}`);
      document.body.dataset.arrows = 'missing';
      return;
    }
    const { u, v } = vectorCodes(png);
    // Climate frames share one reference so lengths compare across months; a day uses its own.
    const reference = climate && clim?.flux_ref ? clim.flux_ref : arrowReference(u, v, meta.uv_encode);
    this.arrows.setField({ u, v, encode: meta.uv_encode, grid: this.manifest.grid, reference });
    const full = `full length is ${formatValue(reference, meta.units, meta.encode)}`;
    this.legend.showArrows(
      climate
        ? `Arrows: divergent energy transport, ${clim!.period.replace('-', '–')} ${meanFlowText(frame)}; ${full}`
        : `Arrows: divergent energy transport; ${full}`,
    );
    document.body.dataset.arrows = 'on';
    if (climate) this.prefetchFrames((f) => climUvUrl(DATA, clim, f, 'flux_e'));
    else this.prefetch((d) => uvUrl(DATA, this.manifest, d, 'flux_e'));
  }

  /**
   * Show a story step: its layer with the anomaly off, its overlays, and fly to its view.
   * (A step's overlays are exactly what it lists: anything not listed is switched off.)
   */
  async showStep(step: StoryStep, level: ParticleChoice['level']): Promise<void> {
    this.mode = 'today';
    this.timebar?.setKind('dates');
    this.particleChoice = { on: step.particles !== null, level: step.particles ?? level };
    this.arrowsOn = step.arrows;
    this.onStateChange?.();
    this.flyTo(step.view);
    await Promise.all([this.select(step.layer), this.updateParticles(), this.updateArrows()]);
  }

  /** Move the map; reduced-motion users get a jump, as MapLibre does for non-essential moves. */
  flyTo(view: StoryView): void {
    this.map.flyTo({ center: [view.lng, view.lat], zoom: view.zoom, duration: 1800, essential: false });
  }

  /** Set the mode and frame before the first draw, without drawing. */
  setModeFlags(mode: Mode, frame: Frame): void {
    this.mode = mode;
    this.frame = frame;
  }

  /** Switch timescale. The layer stays unless it can't show the mode (select resolves that). */
  async setMode(mode: Mode): Promise<void> {
    this.mode = mode;
    this.timebar?.setKind(mode === 'climate' ? 'frames' : 'dates');
    this.onStateChange?.();
    await Promise.all([this.select(this.layerId || DEFAULT_LAYER), this.updateParticles(), this.updateArrows(), this.updateReadout(), this.updateZonal()]);
  }

  async setFrame(frame: Frame): Promise<void> {
    this.frame = frame;
    this.onStateChange?.();
    await Promise.all([
      this.select(this.layerId || DEFAULT_LAYER),
      this.updateParticles(),
      this.updateArrows(),
      this.updateReadout(),
      this.updateZonal(),
    ]);
  }

  setParticles(choice: ParticleChoice): Promise<void> {
    this.particleChoice = choice;
    this.onStateChange?.();
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
    const climate = this.mode === 'climate';
    const clim = this.manifest.clim;
    const frame = this.frame;
    const date = this.date;
    const url = climate ? climUvUrl(DATA, clim, frame, level) : uvUrl(DATA, this.manifest, date, level);
    let png: DecodedPng | null = null;
    if (url) {
      try {
        png = await this.load(url);
      } catch {
        png = null;
      }
    }
    if (request !== this.windRequest) return; // a later change won
    if (!png) {
      this.wind = null;
      this.particles.setWind(null);
      this.legend.showWind(
        climate ? `No mean flow at ${LEVEL_LABELS[level]} for ${frameName(frame)}` : `No ${LEVEL_LABELS[level]} wind for ${date}`,
      );
      document.body.dataset.particles = 'missing';
      return;
    }
    const speedHi = meta.display === 'auto' ? meta.encode.hi : meta.display[1];
    this.particles.setWind({ width: png.width, height: png.height, rgba: png.data, encode: meta.uv_encode, speedHi });
    this.wind = { level, mean: climate, ...vectorCodes(png) };
    this.legend.showWind(this.windCaption());
    document.body.dataset.particles = level;
    if (climate) this.prefetchFrames((f) => climUvUrl(DATA, clim, f, level));
    else this.prefetch((d) => uvUrl(DATA, this.manifest, d, level));
  }

  private windCaption(): string {
    if (!this.wind) return '';
    const level = LEVEL_LABELS[this.wind.level];
    if (!this.wind.mean) return `Particles: wind at ${level} (daily mean)`;
    const period = (this.manifest.clim?.period ?? '1991-2020').replace('-', '–');
    return `Particles: mean flow at ${level}, ${period} ${meanFlowText(this.frame)}`;
  }

  async select(layer: string): Promise<void> {
    const meta = this.manifest.layers[layer];
    if (!meta) return;
    const request = ++this.request;
    const date = this.date;
    this.menu.setSelected(layer);
    const resolved = resolveMode(this.manifest, layer, this.mode);
    const mode = resolved.mode;
    if (mode !== this.mode) {
      this.mode = mode;
      this.timebar?.setKind(mode === 'climate' ? 'frames' : 'dates');
      void this.updateParticles();
      void this.updateArrows();
      void this.updateReadout();
      void this.updateZonal();
    }
    const frame = this.frame;
    const view = mode === 'anom' ? anomalyView(meta) : meta;
    const clim = this.manifest.clim;
    const url = (d: string) =>
      mode === 'anom' ? anomalyUrl(DATA, this.manifest, d, layer)
        : mode === 'climate' ? climUrl(DATA, clim!, d, layer)
          : fieldUrl(DATA, this.manifest, d, layer);
    // Climate maps are indexed by frame, the others by date.
    const key = mode === 'climate' ? frame : date;
    let field: DecodedPng;
    try {
      field = await this.load(url(key));
    } catch (e) {
      if (request === this.request) {
        this.codes = null;
        this.layerId = layer;
        this.legend.showMessage(`No data for ${meta.title} on ${key} (${e instanceof Error ? e.message : e})`);
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
    const notes = resolved.switched ? [switchNote(mode)] : [];
    this.legend.show(view, scale, notes, mode === 'anom', timescaleText(mode, frame, date, clim?.period ?? '1991-2020'));
    this.codes = codes;
    this.view = view;
    this.layerId = layer;
    this.modeSwitch?.update(mode, availableModes(this.manifest, layer));
    document.body.dataset.layer = layer;
    document.body.dataset.date = date;
    document.body.dataset.mode = mode;
    document.body.dataset.frame = frame;
    this.onStateChange?.();
    if (mode === 'climate') for (const f of FRAMES) this.load(url(f)).catch(() => undefined);
    else this.prefetch(url);
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
    const label = `${this.wind.mean ? 'Mean wind' : 'Wind'} ${LEVEL_LABELS[this.wind.level]}`;
    this.legend.showWind(w ? `${label}: ${describeWind(w)}` : this.windCaption());
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
  const initial = readState(params, manifest); // validated: a stale or edited link falls back to defaults
  const date = initial.date;
  if (!date) {
    fail('No data has been published yet.');
    return;
  }
  const first = initial.layer;

  const map = new MapLibreMap({
    container: 'map',
    style: baseStyle(),
    center: initial.center,
    zoom: initial.zoom,
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
  const choice = initial.particles;
  const closers: { close: () => void; zonal: () => void } = { close: () => undefined, zonal: () => undefined };
  const readout = new ReadoutPanel(document.getElementById('readout')!, () => closers.close());
  const arrows = new ArrowLayer('arrows');
  const zonalPanel = new ZonalPanel(document.getElementById('zonal')!, () => void closers.zonal());
  const strip = new EngineStrip(document.getElementById('strip')!, (id, opener) => info.open(manifest.layers[id]!, manifest.credits, opener));
  const app = new App(manifest, date, raster, particles, legend, menu, choice, readout, map, arrows, zonalPanel, strip);
  closers.close = () => app.unpin();
  closers.zonal = () => {
    void app.setPanel(false);
    zonalButton.setAttribute('aria-pressed', 'false');
    zonalButton.focus();
  };
  handlers.select = (id) => void app.select(id);
  const overlays = new OverlayControls(manifest, choice, (c) => void app.setParticles(c));
  document.querySelector('#menu .menu-head')!.after(overlays.element);
  const modeSwitch = new ModeSwitch(initial.mode, (m) => void app.setMode(m));
  const arrowSwitch = new ArrowsSwitch(manifest, initial.arrows, (on) => void app.setArrows(on));
  overlays.element.append(arrowSwitch.element);
  document.querySelector('#menu .menu-head')!.after(modeSwitch.element);
  app.modeSwitch = modeSwitch;
  app.setModeFlags(initial.mode, initial.frame);
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
      modeSwitch.update('today', availableModes(manifest, step.layer));
      void app.showStep(step, overlays.choice.level);
    },
    () => undefined, // closing keeps the map as the last step left it
  );
  const tourButton = document.createElement('button');
  tourButton.type = 'button';
  tourButton.className = 'tour-start';
  tourButton.textContent = 'Take the tour';
  tourButton.addEventListener('click', () => {
    setMenuOpen(false); // on phones the sheet would cover the card
    tour.start(0);
  });
  document.querySelector('#menu .menu-head')!.after(tourButton);
  const zonalButton = document.createElement('button');
  zonalButton.type = 'button';
  zonalButton.className = 'zb-open';
  zonalButton.textContent = 'Zonal budget';
  zonalButton.setAttribute('aria-pressed', String(initial.panel));
  zonalButton.setAttribute('aria-controls', 'zonal');
  zonalButton.addEventListener('click', () => {
    const open = !zonalPanel.isOpen;
    zonalButton.setAttribute('aria-pressed', String(open));
    void app.setPanel(open);
  });
  tourButton.after(zonalButton);
  const timebar = new TimeBar(
    document.getElementById('timebar')!, manifest.dates, date, (d) => app.setDate(d), (f) => app.setFrame(f), initial.frame,
  );
  timebar.setKind(initial.mode === 'climate' ? 'frames' : 'dates');
  app.timebar = timebar;

  // On phones the menu is a bottom sheet: opened by the Layers button, closed by Done, Esc, or
  // a tap on the map.
  const toggle = document.getElementById('menu-toggle')!;
  const setMenuOpen = (open: boolean) => {
    document.body.classList.toggle('menu-open', open);
    toggle.setAttribute('aria-expanded', String(open));
  };
  toggle.addEventListener('click', () => setMenuOpen(!document.body.classList.contains('menu-open')));
  document.querySelector('#menu .menu-close')!.addEventListener('click', () => {
    setMenuOpen(false);
    toggle.focus();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.body.classList.contains('menu-open') && !document.querySelector('dialog[open]')) {
      setMenuOpen(false);
      toggle.focus();
    }
  });
  const onPhone = () => window.matchMedia('(max-width: 700px)').matches;

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
  map.on('click', (e) => {
    if (onPhone()) setMenuOpen(false);
    app.pin(e.lngLat.lng, e.lngLat.lat);
  });
  if (initial.pin) app.pin(initial.pin[0], initial.pin[1]);
  if (initial.panel) void app.setPanel(true);
  else void app.updateZonal();
  document.body.dataset.ready = 'true';
  // From here on the address bar follows the app: replaceState, so Back isn't filled with
  // every pan; one write shortly after the last change.
  let timer = 0;
  const writeUrl = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      const query = stateQuery(location.search, app.state());
      try {
        history.replaceState(null, '', `?${query}${location.hash}`);
      } catch {
        // Some embedded or sandboxed contexts refuse; the map works without a URL.
      }
    }, 120);
  };
  app.onStateChange = writeUrl;
  map.on('moveend', writeUrl);
  writeUrl();
  // ?tour=N opens the tour at step N (1-based), for links and tests.
  const tourStep = Number(params.get('tour'));
  if (Number.isInteger(tourStep) && tourStep >= 1 && tourStep <= steps.length) tour.start(tourStep - 1);
}

start().catch((e: unknown) => fail(`Could not load the map: ${e instanceof Error ? e.message : String(e)}`));
