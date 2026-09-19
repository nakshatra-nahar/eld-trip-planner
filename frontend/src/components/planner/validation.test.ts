import { describe, expect, it } from 'vitest'
import { DEFAULT_OPTIONS, fromResolved, type PlannerValues } from './types'
import { liveServerErrors, mapServerDetails } from './validation'

describe('mapServerDetails', () => {
  it('maps nested option errors onto the fuel field', () => {
    expect(mapServerDetails({ 'options.fuel_stop_minutes': ['A valid integer is required.'] })).toEqual({
      fuel: 'A valid integer is required.',
    })
  })
  it('uses the override message for geocoding failures', () => {
    expect(mapServerDetails({ current_location: ['Could not find "qqzz"'] }, 'Pick a suggestion.')).toEqual({
      current: 'Pick a suggestion.',
    })
  })
})

describe('liveServerErrors', () => {
  const rejected: PlannerValues = {
    current: { text: 'qqzz', selected: null },
    pickup: fromResolved('Tulsa, OK', 36.15, -95.99),
    dropoff: fromResolved('Dallas, TX', 32.78, -96.8),
    cycleUsed: '10',
    startTime: '2026-09-21T06:00',
    options: { ...DEFAULT_OPTIONS, fuel_stop_minutes: 300 },
  }
  const errors = { current: 'Not found.', fuel: 'Too long.' }

  it('keeps errors while their fields are unchanged', () => {
    expect(liveServerErrors(errors, rejected, { ...rejected, cycleUsed: '12' })).toEqual(errors)
  })

  it('clears an error as soon as its field is edited', () => {
    expect(liveServerErrors(errors, rejected, { ...rejected, current: { text: 'qqz', selected: null } })).toEqual({ fuel: 'Too long.' })
    expect(liveServerErrors(errors, rejected, { ...rejected, current: fromResolved('qqzz', 1, 2) })).toEqual({ fuel: 'Too long.' })
    expect(liveServerErrors(errors, rejected, { ...rejected, options: DEFAULT_OPTIONS })).toEqual({ current: 'Not found.' })
  })

  it('shows nothing without a rejected snapshot', () => {
    expect(liveServerErrors(errors, null, rejected)).toEqual({})
  })
})
