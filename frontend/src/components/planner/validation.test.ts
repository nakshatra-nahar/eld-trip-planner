import { describe, expect, it } from 'vitest'
import { mapServerDetails } from './validation'

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
