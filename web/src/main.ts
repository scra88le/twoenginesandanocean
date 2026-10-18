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
import { RasterLayer } from './layers/raster';
import { Legend } from './legend';
import { fieldUrl, loadManifest } from './manifest';
import { decodePng } from './png';
import { displayScale } from './scale';

setWorkerUrl(workerUrl);

const DATA = import.meta.env.VITE_DATA_URL ?? '/data';

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

async function start(): Promise<void> {
  if (!document.createElement('canvas').getContext('webgl2')) {
    fail('This map needs WebGL2, which your browser or device does not support.');
    return;
  }
  const manifest = await loadManifest(DATA);
  const params = new URLSearchParams(location.search);
  const layerId = params.get('layer') ?? 'net_toa';
  const date = params.get('date') ?? manifest.dates.at(-1);
  const meta = manifest.layers[layerId];
  if (!meta || !date) {
    fail(`Unknown layer or no data: ${layerId}`);
    return;
  }

  const map = new MapLibreMap({
    container: 'map',
    style: baseStyle(),
    center: parseCenter(params.get('center')) ?? [0.25, 20],
    zoom: Number(params.get('zoom') ?? 1.4),
    renderWorldCopies: true,
    attributionControl: false, // credits are in the footer
  });
  const legend = new Legend(document.getElementById('legend')!);
  document.getElementById('credits')!.textContent =
    `${manifest.credits} Coastlines and borders: Natural Earth (public domain). Map rendering: MapLibre GL JS.`;
  const raster = new RasterLayer('field');

  const [png] = await Promise.all([
    fetch(fieldUrl(DATA, manifest, date, layerId)).then(async (r) => {
      if (!r.ok) throw new Error(`${layerId} for ${date}: HTTP ${r.status}`);
      return decodePng(await r.arrayBuffer());
    }),
    new Promise((resolve) => map.once('load', resolve)),
  ]);
  const codes = scalarCodes(png);
  const scale = displayScale(meta, meta.display === 'auto' ? decodeAll(codes, meta.encode) : undefined);
  map.addLayer(raster, 'coastline-halo');
  raster.setData({ width: png.width, height: png.height, rgb: png.data, encode: meta.encode, scale, lut: lutBytes(meta.colour) });
  legend.show(meta, scale);
  document.getElementById('date')!.textContent = `${date} · ERA5, about 6 days behind real time`;

  map.on('mousemove', (e) => {
    const cell = cellIndex(e.lngLat.lng, e.lngLat.lat, manifest.grid);
    if (!cell) return legend.showValue(null);
    const code = codes[cell.j * manifest.grid.nlon + cell.i]!;
    legend.showValue(decodeAll(Uint16Array.of(code), meta.encode)[0]!, code === MASKED);
  });
  map.on('mouseout', () => legend.showValue(null));
  document.body.dataset.ready = 'true';
}

start().catch((e: unknown) => fail(`Could not load the map: ${e instanceof Error ? e.message : String(e)}`));
