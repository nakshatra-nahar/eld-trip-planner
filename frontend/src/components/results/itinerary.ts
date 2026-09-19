// Pure helpers for the Itinerary tab (unit-tested in itinerary.test.ts).
import { dutyPeriodNote } from '../../lib/dutyPeriods'
import { formatClock, minutesBetween } from '../../lib/format'
import type { DailyLog, DutyStatus, TimelineEvent } from '../../types/api'

export interface ItineraryDay {
  date: string
  log?: DailyLog
  /** Events that start on this day. */
  events: TimelineEvent[]
  /** An event from an earlier day still running at 00:00 (a rest or restart), if any. */
  carried: { event: TimelineEvent; allDay: boolean } | null
  /** Two-duty-period driving note, when the day's driving exceeds 11:00. */
  note: string | null
}

const STATUS_WORDS: Record<DutyStatus, string> = { OFF: 'off duty', SB: 'sleeper berth', D: 'driving', ON: 'on duty' }

/**
 * One group per log sheet (so a whole off-duty day inside a 34-hour restart still shows),
 * plus any day that has events but no sheet.
 */
export function buildItineraryDays(timeline: readonly TimelineEvent[], dailyLogs: readonly DailyLog[]): ItineraryDay[] {
  const dates = new Set(dailyLogs.map((l) => l.date))
  for (const e of timeline) dates.add(e.start.slice(0, 10))
  return [...dates].sort().map((date) => {
    const dayStart = `${date}T00:00`
    const running = timeline.filter((e) => e.start < dayStart && e.end > dayStart).at(-1)
    return {
      date,
      log: dailyLogs.find((l) => l.date === date),
      events: timeline.filter((e) => e.start.slice(0, 10) === date),
      carried: running ? { event: running, allDay: minutesBetween(dayStart, running.end) >= 1440 } : null,
      note: dutyPeriodNote(timeline, date),
    }
  })
}

/** "34-hour restart continues (off duty all day)" or "10-hour rest continues until 04:45". */
export function carriedLabel({ event, allDay }: NonNullable<ItineraryDay['carried']>): string {
  const base = event.label.replace(/\s*\(.*\)$/, '')
  return allDay
    ? `${base} continues (${STATUS_WORDS[event.status]} all day)`
    : `${base} continues until ${formatClock(event.end)}`
}
