import type { Grid } from './manifest';

/** The cell containing a point, wrapping longitude; null outside the grid's latitudes. */
export function cellIndex(lng: number, lat: number, g: Grid): { i: number; j: number } | null {
  const west = g.lon0 - g.step / 2;
  const north = g.lat0 + g.step / 2;
  const j = Math.floor((north - lat) / g.step);
  if (j < 0 || j >= g.nlat) return null;
  const i = (((Math.floor((lng - west) / g.step)) % g.nlon) + g.nlon) % g.nlon;
  return { i, j };
}
