// Shared API contract between the Django backend and the React frontend.
// The backend's JSON must match these types exactly (snake_case keys).
// Times are local "home terminal" wall-clock strings: "YYYY-MM-DDTHH:MM" (no zone).

export type DutyStatus = 'OFF' | 'SB' | 'D' | 'ON'

export type EventKind =
  | 'drive'
  | 'pre_trip'
  | 'post_trip'
  | 'pickup'
  | 'dropoff'
  | 'fuel'
  | 'break'
  | 'rest'
  | 'restart'

export type LngLat = [number, number] // [lon, lat]

// ---------- Request ----------

export interface LocationInput {
  label?: string // display label chosen from autocomplete
  lat?: number
  lon?: number
  query?: string // free text to geocode server-side when lat/lon are absent
}

export interface PlanOptions {
  include_inspections: boolean // 30-min pre-trip at each duty-period start, 15-min post-trip before each rest and at trip end (API default false: not in the brief)
  rest_status: 'SB' | 'OFF' // duty status for 10-hour rests (34-hour restarts are always OFF)
  fuel_stop_minutes: number // on-duty minutes per fuel stop (default 30)
}

export interface PlanRequest {
  current_location: LocationInput
  pickup_location: LocationInput
  dropoff_location: LocationInput
  current_cycle_used_hours: number // 0..70
  start_time: string // "YYYY-MM-DDTHH:MM" local home-terminal time
  options?: Partial<PlanOptions>
}

// ---------- Response ----------

export interface ResolvedLocation {
  label: string
  lat: number
  lon: number
}

export interface Instruction {
  text: string // e.g. "Turn left onto Main St", "Merge onto I 55 S"
  maneuver: string // OSRM maneuver type: depart, turn, merge, on ramp, off ramp, fork, end of road, roundabout, rotary, continue, new name, arrive, ...
  modifier: string // left, right, slight left, straight, uturn, ... ("" if none)
  road: string // road name/ref, "" if unknown
  distance_miles: number
  duration_minutes: number
  location: LngLat
}

export interface RouteLeg {
  from_role: 'current' | 'pickup'
  to_role: 'pickup' | 'dropoff'
  distance_miles: number
  duration_hours: number // truck-adjusted driving time
  geometry: LngLat[] // simplified for display
  instructions: Instruction[]
}

export interface RouteInfo {
  distance_miles: number
  duration_hours: number // truck-adjusted total driving time
  geometry: LngLat[] // full route, simplified for display
  legs: RouteLeg[] // always 2 legs: current->pickup, pickup->dropoff (leg 0 may be ~0 miles)
  provider: string // e.g. "Valhalla truck (valhalla1.openstreetmap.de)" or "OSRM (router.project-osrm.org)"
  truck_routing: boolean // true when every leg was routed with a truck profile (false = car-network fallback, also used when the truck route detours badly; see warnings)
}

export interface PlaceRef {
  lat: number
  lon: number
  name: string // "City, ST" style label, e.g. "Joliet, IL" or "I 80 near Joliet, IL"
  city?: string // the "City, ST" part of name, e.g. "Joliet, IL" (always sent by the API)
  road?: string // highway ref when the place is on one, e.g. "I 80" (omitted otherwise)
  tz?: string // IANA time zone of the place, e.g. "America/New_York" (always sent by the API)
}

export interface TimelineEvent {
  id: string // "e1", "e2", ...
  kind: EventKind
  status: DutyStatus
  label: string // human label, e.g. "Driving", "30-minute break", "10-hour rest (sleeper berth)"
  start: string // "YYYY-MM-DDTHH:MM"
  end: string
  duration_hours: number
  miles: number // miles driven during this event (0 for non-driving)
  start_mile: number // cumulative trip miles at event start
  end_mile: number
  leg_index: number // 0 = current->pickup, 1 = pickup->dropoff
  start_location: PlaceRef
  end_location: PlaceRef
  local_start?: string // wall-clock time at start_location's zone "YYYY-MM-DDTHH:MM" (always sent)
  local_end?: string // wall-clock time at end_location's zone (always sent)
  start_tz_abbr?: string // e.g. "EDT" (always sent)
  end_tz_abbr?: string // (always sent)
  reason?: string // why this stop happens (always sent for non-driving events), e.g. "11-hour driving limit reached"
}

export interface Stop {
  id: string // same id as the TimelineEvent it came from
  kind: Exclude<EventKind, 'drive'>
  status: DutyStatus
  label: string
  start: string
  end: string
  duration_hours: number
  mile_marker: number
  day_number: number // 1-based log sheet index the stop starts on
  location: PlaceRef
  local_start?: string // wall-clock time in the stop's own time zone (always sent)
  local_end?: string // (always sent)
  local_tz_abbr?: string // e.g. "EDT" (always sent)
  reason?: string // why this stop happens (always sent for non-driving events)
}

export interface LogSegment {
  status: DutyStatus
  start_minute: number // 0..1440 minutes from local midnight
  end_minute: number // segments are contiguous, cover 0..1440, consecutive same-status merged
}

export interface LogRemark {
  start_minute: number // where the bracket/remark starts on this sheet
  end_minute: number // end of the bracketed (non-driving) period; == start_minute for a flag (trip start/end)
  status: DutyStatus
  location: string // "City, ST", or "I 80 near City, ST" on a highway (PlaceRef.name)
  city?: string // PlaceRef.city (always sent by the API)
  road?: string // PlaceRef.road (omitted when not on a highway)
  note: string // activity, e.g. "Pickup", "Fuel", "10-hour rest (cont.)", or a flag's "Start of trip: driving" / "End of trip: off duty"
}

export interface DailyLog {
  date: string // "YYYY-MM-DD"
  day_number: number // 1-based
  total_miles: number // miles driven on this calendar day
  segments: LogSegment[]
  totals: Record<DutyStatus, number> // hours per status; sums to 24
  remarks: LogRemark[]
  on_duty_hours: number // D + ON (recap "total lines 3 & 4")
  cycle_hours_used: number // hours used in the 70h/8-day cycle at end of this day (conservative: no roll-off)
  cycle_hours_available: number // 70 - cycle_hours_used, floored at 0
  from_location: string // first location of the day
  to_location: string // last location of the day
}

export interface TripSummary {
  total_miles: number
  total_driving_hours: number
  total_on_duty_hours: number // driving + on-duty-not-driving during the trip
  trip_duration_hours: number // start to end of the final event
  start_time: string
  end_time: string
  num_days: number // number of log sheets
  num_fuel_stops: number
  num_breaks: number // 30-min breaks
  num_rests: number // 10-hour rests
  num_restarts: number // 34-hour restarts
  cycle_hours_used_at_end: number
  cycle_hours_available_at_end: number
}

export interface PlanResponse {
  input: {
    current_location: ResolvedLocation
    pickup_location: ResolvedLocation
    dropoff_location: ResolvedLocation
    current_cycle_used_hours: number
    start_time: string
    options: PlanOptions
    home_timezone: string // IANA zone of the current location = home-terminal time used on every log sheet
    home_tz_abbr: string // abbreviation at trip start, e.g. "CDT"
  }
  route: RouteInfo
  timeline: TimelineEvent[]
  stops: Stop[]
  daily_logs: DailyLog[]
  summary: TripSummary
  assumptions: string[]
  warnings: string[]
}

export interface ApiError {
  error: string // human-readable message
  code: string // "validation_error" | "geocode_failed" | "route_not_found" | "upstream_unavailable" | "rate_limited" | "payload_too_large" | "not_found" | "internal_error"
  details?: Record<string, string[]>
}

// ---------- Geocoding ----------

export interface GeocodeResult {
  label: string // "Chicago, Illinois, United States"
  short_label: string // "Chicago, IL"
  lat: number
  lon: number
}

export interface GeocodeResponse {
  results: GeocodeResult[]
}

export interface ReverseGeocodeResponse {
  result: GeocodeResult | null
}

// ---------- Log sheet header (frontend-only, user-entered, persisted locally) ----------

export interface LogHeaderDetails {
  driver_name: string
  co_driver: string
  carrier_name: string
  main_office: string
  home_terminal: string
  truck_number: string
  trailer_number: string
  shipping_doc: string // DVL / manifest number, or "Shipper & commodity"
}
