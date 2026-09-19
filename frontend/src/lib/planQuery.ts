// Shareable plan URLs: a PlanRequest <-> a compact, readable query string, e.g.
// ?from=Chicago,%20IL@41.8781,-87.6298&pickup=...&to=...&cycle=10&start=2026-09-21T06:00
// Options are written only when they differ from the defaults. Responses are cached in
// sessionStorage under the canonical query, so Back/Forward and reloads skip the API.
import type { LocationInput, PlanOptions, PlanRequest, PlanResponse } from '../types/api'
import { isValidWallTime } from './format'

const DEFAULT_OPTIONS: PlanOptions = { include_inspections: true, rest_status: 'SB', fuel_stop_minutes: 30 }

/** Query keys owned by the plan; anything else in the URL (e.g. ?demo=) is left alone. */
export const PLAN_KEYS = ['from', 'pickup', 'to', 'cycle', 'start', 'insp', 'rest', 'fuel'] as const

// encodeURIComponent, but keep the characters that make the URL readable and are safe in a query value.
const enc = (value: string) =>
  encodeURIComponent(value).replace(/%40/g, '@').replace(/%2C/gi, ',').replace(/%3A/gi, ':').replace(/%2F/gi, '/')

const coord = (n: number) => String(Number(n.toFixed(4)))

function encodeLocation(loc: LocationInput): string {
  const label = (loc.label ?? loc.query ?? '').trim()
  return loc.lat !== undefined && loc.lon !== undefined ? `${label}@${coord(loc.lat)},${coord(loc.lon)}` : label
}

const COORDS = /^(.*)@(-?\d{1,3}(?:\.\d+)?),(-?\d{1,3}(?:\.\d+)?)$/

function decodeLocation(raw: string | null): LocationInput | null {
  const value = raw?.trim()
  if (!value) return null
  const m = COORDS.exec(value)
  if (!m) return { query: value }
  const lat = Number(m[2])
  const lon = Number(m[3])
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null
  const label = m[1].trim()
  return { label: label || `${lat}, ${lon}`, lat, lon }
}

/** The plan part of a URL query (no leading "?"), with options omitted when default. */
export function encodePlanQuery(request: PlanRequest): string {
  const options = { ...DEFAULT_OPTIONS, ...request.options }
  const parts: Array<[string, string]> = [
    ['from', encodeLocation(request.current_location)],
    ['pickup', encodeLocation(request.pickup_location)],
    ['to', encodeLocation(request.dropoff_location)],
    ['cycle', String(request.current_cycle_used_hours)],
    ['start', request.start_time],
  ]
  if (!options.include_inspections) parts.push(['insp', '0'])
  if (options.rest_status !== DEFAULT_OPTIONS.rest_status) parts.push(['rest', options.rest_status])
  if (options.fuel_stop_minutes !== DEFAULT_OPTIONS.fuel_stop_minutes) parts.push(['fuel', String(options.fuel_stop_minutes)])
  return parts.map(([k, v]) => `${k}=${enc(v)}`).join('&')
}

/** The PlanRequest in a URL query, or null when the plan keys are missing or invalid. */
export function decodePlanQuery(search: string): PlanRequest | null {
  const params = new URLSearchParams(search)
  const current = decodeLocation(params.get('from'))
  const pickup = decodeLocation(params.get('pickup'))
  const dropoff = decodeLocation(params.get('to'))
  const cycleText = params.get('cycle') ?? '0'
  const cycle = Number(cycleText)
  const start = params.get('start') ?? ''
  if (!current || !pickup || !dropoff || cycleText.trim() === '' || !(cycle >= 0 && cycle <= 70) || !isValidWallTime(start)) {
    return null
  }
  const fuel = Number(params.get('fuel') ?? DEFAULT_OPTIONS.fuel_stop_minutes)
  return {
    current_location: current,
    pickup_location: pickup,
    dropoff_location: dropoff,
    current_cycle_used_hours: cycle,
    start_time: start,
    options: {
      include_inspections: params.get('insp') !== '0',
      rest_status: params.get('rest') === 'OFF' ? 'OFF' : 'SB',
      fuel_stop_minutes: Number.isInteger(fuel) ? fuel : DEFAULT_OPTIONS.fuel_stop_minutes,
    },
  }
}

/** The request that reproduces a plan: its resolved locations, so a shared link never re-geocodes. */
export function requestFromPlan(plan: PlanResponse): PlanRequest {
  const { input } = plan
  const loc = ({ label, lat, lon }: PlanResponse['input']['current_location']): LocationInput => ({ label, lat, lon })
  return {
    current_location: loc(input.current_location),
    pickup_location: loc(input.pickup_location),
    dropoff_location: loc(input.dropoff_location),
    current_cycle_used_hours: input.current_cycle_used_hours,
    start_time: input.start_time,
    options: input.options,
  }
}

/** `search` with the plan keys replaced by `planQuery` (or removed when null); other keys are kept. */
export function withPlanQuery(search: string, planQuery: string | null): string {
  const kept = search
    .replace(/^\?/, '')
    .split('&')
    .filter((part) => part && !(PLAN_KEYS as readonly string[]).includes(decodeURIComponent(part.split('=')[0])))
  const query = [...kept, ...(planQuery ? [planQuery] : [])].join('&')
  return query ? `?${query}` : ''
}

// ---------- Response cache ----------

const CACHE_PREFIX = 'routelog.plan.v1:'

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem' | 'key' | 'length'>

function session(): StorageLike | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function readCachedPlan(planQuery: string, storage: StorageLike | null = session()): PlanResponse | null {
  try {
    const raw = storage?.getItem(CACHE_PREFIX + planQuery)
    return raw ? (JSON.parse(raw) as PlanResponse) : null
  } catch {
    return null
  }
}

/** Best effort: when storage is full, drop the older cached plans and try once more. */
export function writeCachedPlan(planQuery: string, plan: PlanResponse, storage: StorageLike | null = session()): void {
  if (!storage) return
  const value = JSON.stringify(plan)
  try {
    storage.setItem(CACHE_PREFIX + planQuery, value)
  } catch {
    try {
      const stale: string[] = []
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i)
        if (key?.startsWith(CACHE_PREFIX)) stale.push(key)
      }
      stale.forEach((key) => storage.removeItem(key))
      storage.setItem(CACHE_PREFIX + planQuery, value)
    } catch {
      // Caching is a convenience; the URL alone can still re-plan the trip.
    }
  }
}
