/**
 * The ONE place where backend GeoJSON order [lng, lat] becomes Leaflet's [lat, lng].
 */
import type { LngLat } from "../api/types";

export type LatLngTuple = [number, number];

export function toLatLng([lng, lat]: LngLat | readonly [number, number]): LatLngTuple {
  return [lat, lng];
}

/** [[south, west], [north, east]] in Leaflet order, or null for no points. */
export function boundsOf(points: Iterable<LngLat>): [LatLngTuple, LatLngTuple] | null {
  let minLat = Infinity;
  let minLng = Infinity;
  let maxLat = -Infinity;
  let maxLng = -Infinity;
  for (const [lng, lat] of points) {
    minLat = Math.min(minLat, lat);
    maxLat = Math.max(maxLat, lat);
    minLng = Math.min(minLng, lng);
    maxLng = Math.max(maxLng, lng);
  }
  if (!Number.isFinite(minLat)) return null;
  return [
    [minLat, minLng],
    [maxLat, maxLng],
  ];
}
