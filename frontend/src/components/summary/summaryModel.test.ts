import { describe, expect, it } from 'vitest'
import type { PlanResponse, TimelineEvent } from '../../types/api'
import { dayLabels, inspectionHours, routingLabel } from './summaryModel'

describe('routingLabel', () => {
  it('names the truck router when every leg was truck-routed', () => {
    expect(routingLabel({ truck_routing: true, provider: 'Valhalla truck (valhalla1.openstreetmap.de)' })).toEqual({
      truck: true,
      label: 'Truck-routed (Valhalla)',
    })
  })
  it('flags the car-network fallback', () => {
    expect(routingLabel({ truck_routing: false, provider: 'OSRM (router.project-osrm.org)' })).toEqual({
      truck: false,
      label: 'Car network (OSRM fallback)',
    })
  })
})

describe('inspectionHours', () => {
  it('sums pre- and post-trip inspections only', () => {
    const e = (kind: TimelineEvent['kind'], duration_hours: number) => ({ kind, duration_hours }) as TimelineEvent
    const plan = { timeline: [e('pre_trip', 0.5), e('drive', 8), e('post_trip', 0.25), e('pre_trip', 0.5), e('fuel', 0.5)] } as PlanResponse
    expect(inspectionHours(plan)).toBe(1.25)
  })
})

describe('dayLabels', () => {
  const at = (...lefts: number[]) => lefts.map((left, i) => ({ left, label: `Day ${i + 2}` }))
  it('labels every day when they are far enough apart', () => {
    expect(dayLabels(at(15, 35, 55)).map((l) => l.label)).toEqual(['Day 1', 'Day 2', 'Day 3', 'Day 4'])
  })
  it('keeps Day 2 over a short Day 1', () => {
    expect(dayLabels(at(5, 50))).toEqual([{ left: 5, label: 'Day 2' }, { left: 50, label: 'Day 3' }])
  })
  it('drops a label that would crowd the previous one', () => {
    expect(dayLabels(at(20, 25, 60)).map((l) => l.label)).toEqual(['Day 1', 'Day 2', 'Day 4'])
  })
  it('needs extra room for a right-aligned label at the end', () => {
    expect(dayLabels(at(30, 80, 96)).map((l) => l.label)).toEqual(['Day 1', 'Day 2', 'Day 3'])
    expect(dayLabels(at(30, 60, 96)).map((l) => l.label)).toEqual(['Day 1', 'Day 2', 'Day 3', 'Day 4'])
  })
})
