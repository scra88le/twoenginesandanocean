// The AMOC belt drawn on the map: the polygons of `beltFeatures`, two arrows per 5° of latitude
// (orange upper limb, blue deep limb), as ordinary MapLibre fill layers so they scale with the map.
import type { Map as MapLibreMap, GeoJSONSource } from 'maplibre-gl';
import type { BeltFeatureCollection } from '../ocean';

const SOURCE = 'ocean-belt';
const EMPTY: BeltFeatureCollection = { type: 'FeatureCollection', features: [] };

export class BeltOverlay {
  constructor(private readonly map: MapLibreMap) {}

  /** Add the source and layers (once the style is loaded). */
  add(): void {
    this.map.addSource(SOURCE, { type: 'geojson', data: EMPTY });
    this.map.addLayer({
      id: 'ocean-belt-fill',
      type: 'fill',
      source: SOURCE,
      paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': 0.88 },
    });
    this.map.addLayer({
      id: 'ocean-belt-line',
      type: 'line',
      source: SOURCE,
      paint: { 'line-color': '#10131a', 'line-width': 1 },
    });
  }

  /** Draw these arrows, or none. */
  set(data: BeltFeatureCollection | null): void {
    (this.map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(data ?? EMPTY);
  }

  /** How many arrows are drawn (for the tests). */
  get count(): number {
    const src = this.map.getSource(SOURCE) as (GeoJSONSource & { _data?: BeltFeatureCollection }) | undefined;
    return src?._data?.features.length ?? 0;
  }
}
