// Driving per duty period within one calendar day. A day can hold the end of one duty period
// and the start of the next (split by a 10-hour rest or a 34-hour restart), so its Driving
// line may legally exceed 11:00; the note explains that on the sheet and in the itinerary.
import type { TimelineEvent } from '../types/api'
import { formatMinutesClock, minutesBetween } from './format'

const DAY_MINUTES = 1440
const MAX_DRIVING_MINUTES = 11 * 60

/** Driving minutes on `date` ("YYYY-MM-DD") for each duty period that drove that day, in order. */
export function drivingByDutyPeriod(timeline: readonly TimelineEvent[], date: string): number[] {
  const dayStart = `${date}T00:00`
  const byPeriod = new Map<number, number>()
  let period = 0
  for (const e of timeline) {
    if (e.kind === 'rest' || e.kind === 'restart') {
      period++
      continue
    }
    if (e.kind !== 'drive') continue
    const from = Math.max(0, minutesBetween(dayStart, e.start))
    const to = Math.min(DAY_MINUTES, minutesBetween(dayStart, e.end))
    if (to > from) byPeriod.set(period, (byPeriod.get(period) ?? 0) + to - from)
  }
  return [...byPeriod.entries()].sort(([a], [b]) => a - b).map(([, minutes]) => minutes)
}

/**
 * "2 duty periods today: 11:00 + 1:15 driving; each ≤ 11 h (§395.3)" when the day's driving
 * exceeds 11:00 across two or more duty periods; otherwise null.
 */
export function dutyPeriodNote(timeline: readonly TimelineEvent[], date: string): string | null {
  const periods = drivingByDutyPeriod(timeline, date)
  const total = periods.reduce((a, b) => a + b, 0)
  if (periods.length < 2 || total <= MAX_DRIVING_MINUTES) return null
  return `${periods.length} duty periods today: ${periods.map(formatMinutesClock).join(' + ')} driving; each ≤ 11 h (§395.3)`
}
