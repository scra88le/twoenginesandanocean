import type { StyleSpecification } from 'maplibre-gl';

// Dark background plus public-domain Natural Earth 1:50m coastlines and borders, drawn over
// the data. No tile service or API key is needed.
/**
 * A file from /public as an absolute URL, wherever the site is hosted. MapLibre loads GeoJSON
 * in a worker, which would resolve a relative URL against the worker's own location, so the
 * URL must be absolute; and a hard-coded "/basemap/..." breaks when the site is served from a
 * sub-path (GitHub project pages).
 */
export function assetUrl(path: string, base = import.meta.env.BASE_URL, page = document.baseURI): string {
  return new URL(`${base}${path}`, page).href;
}

export function baseStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      coastline: { type: 'geojson', data: assetUrl('basemap/coastline.geojson') },
      borders: { type: 'geojson', data: assetUrl('basemap/borders.geojson') },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#0b0e14' } },
      // A dark outline under the light lines keeps them visible over light colour scales.
      { id: 'coastline-halo', type: 'line', source: 'coastline', paint: { 'line-color': '#0b0e14', 'line-width': 2.2, 'line-opacity': 0.55 } },
      { id: 'coastline', type: 'line', source: 'coastline', paint: { 'line-color': '#d7dbe2', 'line-width': 0.7, 'line-opacity': 0.75 } },
      { id: 'borders', type: 'line', source: 'borders', paint: { 'line-color': '#c0c5ce', 'line-width': 0.5, 'line-opacity': 0.45, 'line-dasharray': [3, 2] } },
    ],
  };
}
