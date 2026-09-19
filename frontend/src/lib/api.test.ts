import { describe, expect, it } from 'vitest'
import { ApiRequestError, describeError } from './api'

describe('describeError', () => {
  it('names a geocoder outage as place search, not routing', () => {
    const err = new ApiRequestError('Geocoding service unavailable (photon, nominatim).', 'upstream_unavailable', 502)
    expect(describeError(err).title).toBe('Place search is busy')
  })
  it('keeps the routing copy for a router outage', () => {
    const err = new ApiRequestError('Routing timed out. Please try again.', 'upstream_unavailable', 502)
    expect(describeError(err).title).toBe('Routing service is busy')
  })
})
