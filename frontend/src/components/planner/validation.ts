import { isValidWallTime } from '../../lib/format'
import type { PlannerErrors, PlannerValues } from './types'

/** Same bounds as the backend serializer (PlanOptionsSerializer.fuel_stop_minutes). */
export const FUEL_MINUTES = { min: 5, max: 240 } as const

export function validatePlanner(values: PlannerValues): PlannerErrors {
  const errors: PlannerErrors = {}
  const need = (key: 'current' | 'pickup' | 'dropoff', what: string) => {
    if (values[key].text.trim().length < 2) errors[key] = `Enter the ${what}.`
  }
  need('current', 'current location')
  need('pickup', 'pickup location')
  need('dropoff', 'dropoff location')

  const p = values.pickup.selected
  const d = values.dropoff.selected
  if (!errors.dropoff && p && d && Math.abs(p.lat - d.lat) < 1e-4 && Math.abs(p.lon - d.lon) < 1e-4) {
    errors.dropoff = 'Dropoff must be different from pickup.'
  }

  const cycleText = values.cycleUsed.trim()
  const cycle = Number(cycleText)
  if (cycleText === '' || Number.isNaN(cycle)) errors.cycleUsed = 'Enter the hours already used (0-70).'
  else if (cycle < 0 || cycle > 70) errors.cycleUsed = 'Cycle hours must be between 0 and 70.'

  if (!isValidWallTime(values.startTime)) errors.startTime = 'Choose a valid start date and time.'

  const fuel = values.options.fuel_stop_minutes
  if (!Number.isInteger(fuel) || fuel < FUEL_MINUTES.min || fuel > FUEL_MINUTES.max) {
    errors.fuel = `Fuel stop must be a whole number of minutes, ${FUEL_MINUTES.min}-${FUEL_MINUTES.max}.`
  }

  return errors
}

/**
 * Maps backend error details (keys from PlanRequest, nested ones flattened as
 * "options.fuel_stop_minutes") onto form fields. `override` replaces the server's wording,
 * e.g. for geocoding failures where the field itself is the message.
 */
export function mapServerDetails(details?: Record<string, string[]>, override?: string): PlannerErrors {
  if (!details) return {}
  const map: Record<string, keyof PlannerErrors> = {
    current_location: 'current',
    pickup_location: 'pickup',
    dropoff_location: 'dropoff',
    current_cycle_used_hours: 'cycleUsed',
    start_time: 'startTime',
    fuel_stop_minutes: 'fuel',
    'options.fuel_stop_minutes': 'fuel',
  }
  const errors: PlannerErrors = {}
  for (const [key, messages] of Object.entries(details)) {
    const field = map[key] ?? Object.entries(map).find(([k]) => key.startsWith(k))?.[1]
    if (field && messages.length) errors[field] = override ?? messages.join(' ')
  }
  return errors
}
