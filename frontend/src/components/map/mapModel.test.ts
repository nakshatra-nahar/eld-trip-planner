import { describe, expect, it } from 'vitest'
import { clusterPlaces, type MapPlace, nudgeFromPin } from './mapModel'
import type { Stop } from '../../types/api'

describe('nudgeFromPin', () => {
  it('leaves markers that are clear of the pin alone', () => {
    expect(nudgeFromPin([200, 100], [100, 100])).toBeNull()
    expect(nudgeFromPin([100, 150], [100, 100])).toBeNull()
  })

  it('slides a marker on top of the pin to the right, clear of it', () => {
    expect(nudgeFromPin([100, 100], [100, 100])).toEqual([37, 0])
    expect(nudgeFromPin([105, 80], [100, 100])).toEqual([32, 0])
  })

  it('slides a marker left of the pin further left', () => {
    expect(nudgeFromPin([90, 90], [100, 100])).toEqual([-27, 0])
  })

  it('treats ~20 px from the pin outline as too close', () => {
    expect(nudgeFromPin([100 + 17 + 15, 90], [100, 100])).not.toBeNull()
    expect(nudgeFromPin([100 + 17 + 21, 90], [100, 100])).toBeNull()
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
        place('dropoff', 5, [], 'dropoff'),
      ],
      project,
    )
    expect(out.map((p) => p.key)).toEqual(['a', 'b', 'dropoff'])
  })
})
