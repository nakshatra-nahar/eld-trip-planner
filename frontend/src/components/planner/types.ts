import type { GeocodeResult, LocationInput, PlanOptions } from '../../types/api'

export interface LocationValue {
  /** What is typed in the box. */
  text: string
  /** The suggestion the user picked, if any. Cleared as soon as the text is edited. */
  selected: GeocodeResult | null
}

export interface PlannerValues {
  current: LocationValue
  pickup: LocationValue
  dropoff: LocationValue
  /** Kept as text so the field can be cleared while typing. */
  cycleUsed: string
  startTime: string
  options: PlanOptions
}

export type PlannerErrors = Partial<Record<'current' | 'pickup' | 'dropoff' | 'cycleUsed' | 'startTime' | 'fuel', string>>

export const EMPTY_LOCATION: LocationValue = { text: '', selected: null }

export const DEFAULT_OPTIONS: PlanOptions = {
  // Off, as in the API: the brief lists only pickup, drop-off and fueling as on-duty stops.
  include_inspections: false,
  rest_status: 'SB',
  fuel_stop_minutes: 30,
}

export function toLocationInput(value: LocationValue): LocationInput {
  if (value.selected) {
    return { label: value.selected.short_label, lat: value.selected.lat, lon: value.selected.lon }
  }
  return { query: value.text.trim() }
}

export function fromResolved(label: string, lat: number, lon: number): LocationValue {
  return { text: label, selected: { label, short_label: label, lat, lon } }
}
