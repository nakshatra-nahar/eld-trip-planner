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
  /**
   * Endpoint pins only: stops elsewhere that would sit under this pin at the current zoom (see
   * clusterPlaces). They are listed in the pin's popup instead of drawing a marker under it.
   */
  nearby?: Stop[]
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

/** Stop markers closer than this on screen merge into one marker with a count badge. */
export const CLUSTER_RADIUS_PX = 28

/** Endpoint pins are 34x44 px, anchored at the tip; stop markers are ~30 px circles. */
const PIN = { halfWidth: 17, height: 44 }
const STOP_RADIUS = 16
const CLEARANCE = 4

/**
 * Screen distance (px) from a stop marker's centre to an endpoint pin's outline (the pin's
 * bounding box, which stands above its tip). Returns null when the marker is clear of the pin,
 * i.e. the two would not overlap or touch.
 */
export function pinOverlap(stop: [number, number], pinTip: [number, number]): number | null {
  const [x, y] = stop
  const [px, py] = pinTip
  const nearestX = Math.min(Math.max(x, px - PIN.halfWidth), px + PIN.halfWidth)
  const nearestY = Math.min(Math.max(y, py - PIN.height), py)
  const gap = Math.hypot(x - nearestX, y - nearestY)
  return gap < STOP_RADIUS + CLEARANCE ? gap : null
}

/**
 * Merges markers that would overlap on screen at the current zoom. `project` maps lng/lat to
 * screen px.
 *
 * 1. Stop markers: greedy, most important stop first. Each marker joins the first cluster whose
 *    anchor is within `radius` px, so a cluster sits on its most important stop.
 * 2. A stop cluster that would sit under an endpoint pin joins that pin (its `nearby` list, shown
 *    in the pin's popup) instead of being drawn. Markers never move off their true position:
 *    shifting one sideways put it off the route, and near a coast out to sea.
 */
export function clusterPlaces(
  places: readonly MapPlace[],
  project: (lngLat: LngLat) => [number, number],
  radius = CLUSTER_RADIUS_PX,
): MapPlace[] {
  const stops = places.filter((p) => !p.role).sort((a, b) => byPriority(a.stops[0], b.stops[0]))
  const clusters: { at: [number, number]; place: MapPlace }[] = []
  for (const place of stops) {
    const at = project(place.lngLat)
    const hit = clusters.find((c) => Math.hypot(c.at[0] - at[0], c.at[1] - at[1]) < radius)
    if (hit) hit.place = { ...hit.place, stops: [...hit.place.stops, ...place.stops].sort(byPriority) }
    else clusters.push({ at, place })
  }

  const pins = places.filter((p) => p.role).map((place) => ({ tip: project(place.lngLat), place, nearby: [] as Stop[] }))
  const free: MapPlace[] = []
  for (const cluster of clusters) {
    let best: (typeof pins)[number] | null = null
    let bestGap = Infinity
    for (const pin of pins) {
      const gap = pinOverlap(cluster.at, pin.tip)
      if (gap !== null && gap < bestGap) {
        best = pin
        bestGap = gap
      }
    }
    if (best) best.nearby.push(...cluster.place.stops)
    else free.push(cluster.place)
  }
  return [
    ...free,
    ...pins.map(({ place, nearby }) => (nearby.length ? { ...place, nearby: nearby.sort(byPriority) } : place)),
  ]
}
