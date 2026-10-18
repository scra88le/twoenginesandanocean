import type { StyleSpecification } from 'maplibre-gl';

// Dark background plus public-domain Natural Earth 1:50m coastlines and borders, drawn over
// the data. No tile service or API key is needed.
export function baseStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      coastline: { type: 'geojson', data: '/basemap/coastline.geojson' },
      borders: { type: 'geojson', data: '/basemap/borders.geojson' },
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
