// Pure helpers for the trip summary card (unit-tested in summaryModel.test.ts).
import type { PlanResponse } from '../../types/api'

/** Hours of pre-/post-trip inspection in the plan (0 when inspections are off). */
export function inspectionHours(plan: Pick<PlanResponse, 'timeline'>): number {
  return plan.timeline.filter((e) => e.kind === 'pre_trip' || e.kind === 'post_trip').reduce((a, e) => a + e.duration_hours, 0)
}

/** "Truck-routed (Valhalla)" or "Car network (OSRM fallback)", from route.truck_routing. */
export function routingLabel(route: Pick<PlanResponse['route'], 'truck_routing' | 'provider'>): { truck: boolean; label: string } {
  const truck = route.truck_routing ?? /valhalla/i.test(route.provider)
  const engine = /valhalla/i.test(route.provider) ? 'Valhalla' : /osrm/i.test(route.provider) ? 'OSRM' : route.provider.split(' ')[0]
  return truck
    ? { truck, label: `Truck-routed (${engine})` }
    : { truck, label: `Car network (${engine === 'Valhalla' ? engine : 'OSRM'} fallback)` }
}

export interface DayLabel {
  left: number // % along the bar
  label: string
}

/**
 * Day labels for the duty timeline bar: "Day 1" at the start, then one per midnight, each
 * drawn from its position rightwards. A label that would crowd the one before it (less than
 * `minGap` % apart) is dropped; the midnight lines still show every day.
 */
export function dayLabels(midnights: DayLabel[], minGap = 12): DayLabel[] {
  const out: DayLabel[] = []
  for (const m of [{ left: 0, label: 'Day 1' }, ...midnights]) {
    // A label near the right end is right-aligned, so it needs room for its own width too.
    const gap = m.left > 92 ? 2 * minGap : minGap
    const prev = out[out.length - 1]
    if (prev && m.left - prev.left < gap) {
      // Keep the later day when "Day 1" would crowd "Day 2" (a short first day).
      if (prev.label === 'Day 1' && out.length === 1 && m.left <= 92) out[0] = m
      continue
    }
    out.push(m)
  }
  return out
}
