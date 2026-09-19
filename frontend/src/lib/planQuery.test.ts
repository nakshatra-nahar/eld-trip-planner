import { describe, expect, it } from 'vitest'
import type { PlanRequest, PlanResponse } from '../types/api'
import {
  decodePlanQuery,
  encodePlanQuery,
  readCachedPlan,
  requestFromPlan,
  withPlanQuery,
  writeCachedPlan,
} from './planQuery'

const request: PlanRequest = {
  current_location: { label: 'Chicago, IL', lat: 41.87811, lon: -87.62979 },
  pickup_location: { label: 'St. Louis, MO', lat: 38.627, lon: -90.1994 },
  dropoff_location: { query: 'Dallas TX' },
  current_cycle_used_hours: 10.5,
  start_time: '2026-09-21T06:00',
  options: { include_inspections: true, rest_status: 'SB', fuel_stop_minutes: 30 },
}

describe('encodePlanQuery', () => {
  it('writes a compact, readable query and omits default options', () => {
    expect(encodePlanQuery(request)).toBe(
      'from=Chicago,%20IL@41.8781,-87.6298&pickup=St.%20Louis,%20MO@38.627,-90.1994&to=Dallas%20TX&cycle=10.5&start=2026-09-21T06:00',
    )
  })

  it('writes options that differ from the defaults', () => {
    const q = encodePlanQuery({ ...request, options: { include_inspections: false, rest_status: 'OFF', fuel_stop_minutes: 45 } })
    expect(q.endsWith('&insp=0&rest=OFF&fuel=45')).toBe(true)
  })
})

describe('decodePlanQuery', () => {
  it('round-trips a request (coordinates to 4 dp)', () => {
    const decoded = decodePlanQuery(`?${encodePlanQuery(request)}`)
    expect(decoded).toEqual({
      ...request,
      current_location: { label: 'Chicago, IL', lat: 41.8781, lon: -87.6298 },
    })
  })

  it('round-trips labels containing @, + and &', () => {
    const odd = { ...request, pickup_location: { label: 'Dock @ 5 & A+B, Joliet, IL', lat: 41.5, lon: -88.1 } }
    expect(decodePlanQuery(encodePlanQuery(odd))?.pickup_location).toEqual(odd.pickup_location)
  })

  it('keeps unrelated params working and ignores their order', () => {
    const decoded = decodePlanQuery(`?demo=1&start=2026-09-21T06:00&to=Dallas&pickup=Tulsa&from=Chicago&cycle=0&rest=OFF`)
    expect(decoded?.dropoff_location).toEqual({ query: 'Dallas' })
    expect(decoded?.options).toEqual({ include_inspections: true, rest_status: 'OFF', fuel_stop_minutes: 30 })
  })

  it.each([
    ['a missing location', 'from=A&pickup=B&cycle=1&start=2026-09-21T06:00'],
    ['cycle over 70', 'from=A&pickup=B&to=C&cycle=71&start=2026-09-21T06:00'],
    ['a bad start time', 'from=A&pickup=B&to=C&cycle=1&start=tomorrow'],
    ['bad coordinates', 'from=A@123,4&pickup=B&to=C&cycle=1&start=2026-09-21T06:00'],
    ['no plan at all', 'demo=1'],
  ])('rejects %s', (_, q) => expect(decodePlanQuery(q)).toBeNull())
})

describe('withPlanQuery', () => {
  it('replaces the plan keys and keeps the rest', () => {
    expect(withPlanQuery('?demo=restart&from=X&cycle=3', 'from=Y&cycle=4')).toBe('?demo=restart&from=Y&cycle=4')
    expect(withPlanQuery('?demo=1&from=X', null)).toBe('?demo=1')
    expect(withPlanQuery('?from=X', null)).toBe('')
  })
})

describe('requestFromPlan', () => {
  it('uses the resolved locations and the plan inputs', () => {
    const plan = {
      input: {
        current_location: { label: 'Chicago, IL', lat: 41.8, lon: -87.6 },
        pickup_location: { label: 'Tulsa, OK', lat: 36.1, lon: -95.9 },
        dropoff_location: { label: 'Dallas, TX', lat: 32.7, lon: -96.8 },
        current_cycle_used_hours: 12,
        start_time: '2026-09-21T06:00',
        options: { include_inspections: false, rest_status: 'SB', fuel_stop_minutes: 30 },
        home_timezone: 'America/Chicago',
        home_tz_abbr: 'CDT',
      },
    } as PlanResponse
    expect(encodePlanQuery(requestFromPlan(plan))).toBe(
      'from=Chicago,%20IL@41.8,-87.6&pickup=Tulsa,%20OK@36.1,-95.9&to=Dallas,%20TX@32.7,-96.8&cycle=12&start=2026-09-21T06:00&insp=0',
    )
  })
})

describe('plan cache', () => {
  function fakeStorage(limit = Infinity) {
    const map = new Map<string, string>()
    return {
      map,
      get length() {
        return map.size
      },
      key: (i: number) => [...map.keys()][i] ?? null,
      getItem: (k: string) => map.get(k) ?? null,
      removeItem: (k: string) => void map.delete(k),
      setItem: (k: string, v: string) => {
        if (map.size >= limit) throw new Error('QuotaExceededError')
        map.set(k, v)
      },
    }
  }
  const plan = { summary: { total_miles: 1 } } as PlanResponse

  it('stores and restores a plan by query', () => {
    const storage = fakeStorage()
    writeCachedPlan('q1', plan, storage)
    expect(readCachedPlan('q1', storage)).toEqual(plan)
    expect(readCachedPlan('q2', storage)).toBeNull()
  })

  it('evicts older plans when storage is full', () => {
    const storage = fakeStorage(1)
    writeCachedPlan('q1', plan, storage)
    writeCachedPlan('q2', plan, storage)
    expect(readCachedPlan('q1', storage)).toBeNull()
    expect(readCachedPlan('q2', storage)).toEqual(plan)
  })

  it('never throws without storage', () => {
    expect(() => writeCachedPlan('q', plan, null)).not.toThrow()
    expect(readCachedPlan('q', null)).toBeNull()
  })
})
