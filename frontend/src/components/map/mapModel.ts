// Pure helpers that turn a PlanResponse into things the map draws.
import type { FeatureCollection, LineString } from 'geojson'
import { EVENT_KIND } from '../../lib/duty'
import { placeLabel } from '../../lib/format'
import type { LngLat, PlanResponse, Stop } from '../../types/api'

export type EndpointRole = 'current' | 'pickup' | 'dropoff'

export interface MapPlace {
  /** Stable key for React and popup state. */
  key: string
  lngLat: LngLat
  /** Set for the three trip endpoints. */
  role?: EndpointRole
  title: string
  /** Stops at this location, most important first (by EVENT_KIND priority, then time). */
  stops: Stop[]
}

export type Bounds = [[number, number], [number, number]]

export interface MapFocus {
  /** Increments on every request so re-selecting the same item flies again. */
  nonce: number
  stopId?: string
  lngLat?: LngLat
  bounds?: Bounds
}

export const DEFAULT_VIEW = { longitude: -97.5, latitude: 39.2, zoom: 3.35 }

export function boundsOf(points: LngLat[]): Bounds | null {
  if (!points.length) return null
  let [minX, minY] = points[0]
  let [maxX, maxY] = points[0]
  for (const [x, y] of points) {
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }
  return [
    [minX, minY],
    [maxX, maxY],
  ]
}

/** Rough ground distance in miles; plenty for grouping markers. */
function approxMiles(a: LngLat, b: LngLat): number {
  const dx = (a[0] - b[0]) * 69 * Math.cos((((a[1] + b[1]) / 2) * Math.PI) / 180)
  const dy = (a[1] - b[1]) * 69
  return Math.hypot(dx, dy)
}

const GROUP_RADIUS_MI = 0.75

const byPriority = (a: Stop, b: Stop) =>
  EVENT_KIND[a.kind].priority - EVENT_KIND[b.kind].priority || a.start.localeCompare(b.start)

/**
 * Groups co-located stops (e.g. post-trip + rest + pre-trip) into a single marker,
 * and attaches stops at the trip endpoints to the endpoint pins.
 */
export function buildPlaces(plan: PlanResponse): MapPlace[] {
  const { input } = plan
  const endpoints: MapPlace[] = (
    [
      ['current', input.current_location],
      ['pickup', input.pickup_location],
      ['dropoff', input.dropoff_location],
    ] as const
  ).map(([role, loc]) => ({ key: role, role, lngLat: [loc.lon, loc.lat], title: placeLabel(loc.label), stops: [] }))

  // Current == pickup: keep a single pin (the pickup) at that spot.
  const [current, pickup] = endpoints
  const places = approxMiles(current.lngLat, pickup.lngLat) < GROUP_RADIUS_MI ? endpoints.slice(1) : endpoints

  for (const stop of plan.stops) {
    const at: LngLat = [stop.location.lon, stop.location.lat]
    const home = places.find((p) => approxMiles(p.lngLat, at) < GROUP_RADIUS_MI)
    if (home) home.stops.push(stop)
    else places.push({ key: `s-${stop.id}`, lngLat: at, title: placeLabel(stop.location.name), stops: [stop] })
  }
  for (const p of places) p.stops.sort(byPriority)
  // Endpoints render last so they sit above stop markers.
  return [...places.filter((p) => !p.role), ...places.filter((p) => p.role)]
}

export function routeFeatures(plan: PlanResponse): FeatureCollection<LineString, { leg: number }> {
  return {
    type: 'FeatureCollection',
    features: plan.route.legs
      .map((leg, i) => ({
        type: 'Feature' as const,
        properties: { leg: i },
        geometry: { type: 'LineString' as const, coordinates: leg.geometry },
      }))
      .filter((f) => f.geometry.coordinates.length >= 2),
  }
}
