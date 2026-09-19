import { describe, expect, it } from 'vitest'
import { buildPlaces, clusterPlaces, type MapPlace, pinOverlap } from './mapModel'
import type { PlanResponse } from '../../types/api'
import type { Stop } from '../../types/api'

describe('pinOverlap', () => {
  it('is null for markers clear of the pin', () => {
    expect(pinOverlap([200, 100], [100, 100])).toBeNull()
    expect(pinOverlap([100, 150], [100, 100])).toBeNull()
  })

  it('reports how close a marker on or beside the pin is', () => {
    expect(pinOverlap([100, 100], [100, 100])).toBe(0)
    expect(pinOverlap([105, 80], [100, 100])).toBe(0)
    expect(pinOverlap([100 + 17 + 15, 90], [100, 100])).toBe(15)
    expect(pinOverlap([100 + 17 + 21, 90], [100, 100])).toBeNull()
  })

  it('covers the pin body standing above its tip, not below it', () => {
    expect(pinOverlap([100, 100 - 44 - 10], [100, 100])).toBe(10)
    expect(pinOverlap([100, 100 + 25], [100, 100])).toBeNull()
  })
})

describe('clusterPlaces', () => {
  const stop = (id: string, kind: Stop['kind'], start: string): Stop =>
    ({ id, kind, start, end: start, status: 'ON', label: id, duration_hours: 0.5, location: { lat: 0, lon: 0, name: id }, mile_marker: 0 }) as Stop
  const place = (key: string, x: number, stops: Stop[], role?: MapPlace['role']): MapPlace => ({
    key,
    lngLat: [x, 0],
    title: key,
    stops,
    role,
  })
  const project = ([x]: [number, number]): [number, number] => [x, 0]

  it('merges stop markers that would overlap and keeps the most important on top', () => {
    const out = clusterPlaces(
      [place('a', 0, [stop('fuel', 'fuel', '2026-01-01T10:00')]), place('b', 10, [stop('rest', 'rest', '2026-01-01T12:00')])],
      project,
    )
    expect(out).toHaveLength(1)
    expect(out[0].stops.map((s) => s.id)).toEqual(['rest', 'fuel'])
  })

  it('leaves distant markers and endpoint pins alone', () => {
    const out = clusterPlaces(
      [
        place('a', 0, [stop('fuel', 'fuel', '2026-01-01T10:00')]),
        place('b', 100, [stop('brk', 'break', '2026-01-01T12:00')]),
        place('dropoff', 300, [], 'dropoff'),
      ],
      project,
    )
    expect(out.map((p) => p.key)).toEqual(['a', 'b', 'dropoff'])
  })

  it('folds a stop that would sit under an endpoint pin into that pin, never moving it', () => {
    const brk = stop('brk', 'break', '2026-01-01T12:00')
    const drop = stop('drop', 'dropoff', '2026-01-01T15:00')
    const out = clusterPlaces([place('b', 95, [brk]), place('dropoff', 100, [drop], 'dropoff')], project)
    expect(out).toHaveLength(1)
    expect(out[0].key).toBe('dropoff')
    expect(out[0].lngLat).toEqual([100, 0])
    expect(out[0].stops.map((s) => s.id)).toEqual(['drop'])
    expect(out[0].nearby?.map((s) => s.id)).toEqual(['brk'])
  })

  it('folds a whole stop cluster into the nearest overlapping pin', () => {
    const out = clusterPlaces(
      [
        place('a', 70, [stop('rest', 'rest', '2026-01-01T10:00')]),
        place('b', 60, [stop('fuel', 'fuel', '2026-01-01T09:00')]),
        place('pickup', 40, [], 'pickup'),
        place('dropoff', 80, [], 'dropoff'),
      ],
      project,
    )
    expect(out.map((p) => p.key)).toEqual(['pickup', 'dropoff'])
    expect(out[0].nearby).toBeUndefined()
    expect(out[1].nearby?.map((s) => s.id)).toEqual(['rest', 'fuel'])
  })

  it('keeps a stop just clear of the pin as its own marker, at its own position', () => {
    const out = clusterPlaces([place('b', 100 + 17 + 21, [stop('brk', 'break', '2026-01-01T12:00')]), place('dropoff', 100, [], 'dropoff')], project)
    expect(out.map((p) => [p.key, p.lngLat[0], p.nearby])).toEqual([
      ['b', 138, undefined],
      ['dropoff', 100, undefined],
    ])
  })

  it('does not mutate its input', () => {
    const pin = place('dropoff', 100, [], 'dropoff')
    clusterPlaces([place('b', 99, [stop('brk', 'break', '2026-01-01T12:00')]), pin], project)
    expect(pin.nearby).toBeUndefined()
  })
})

describe('buildPlaces', () => {
  const loc = (label: string, lat: number, lon: number) => ({ label, lat, lon })
  const stopAt = (id: string, kind: Stop['kind'], lat: number, lon: number): Stop =>
    ({ id, kind, start: `2026-01-01T${id}`, end: '', status: 'OFF', label: id, duration_hours: 0.5, location: { lat, lon, name: id }, mile_marker: 0 }) as Stop
  const plan = (stops: Stop[]) =>
    ({
      input: {
        current_location: loc('New York, NY', 40.71, -74.01),
        pickup_location: loc('Chicago, IL', 41.88, -87.63),
        dropoff_location: loc('Los Angeles, CA', 34.05, -118.24),
      },
      stops,
    }) as unknown as PlanResponse

  it('attaches stops at an endpoint to its pin and keeps other stops at their own position', () => {
    const places = buildPlaces(plan([stopAt('10', 'rest', 34.8, -117.11), stopAt('11', 'dropoff', 34.0523, -118.2436)]))
    expect(places.map((p) => [p.key, p.lngLat, p.stops.map((s) => s.id)])).toEqual([
      ['s-10', [-117.11, 34.8], ['10']],
      ['current', [-74.01, 40.71], []],
      ['pickup', [-87.63, 41.88], []],
      ['dropoff', [-118.24, 34.05], ['11']],
    ])
  })
})
