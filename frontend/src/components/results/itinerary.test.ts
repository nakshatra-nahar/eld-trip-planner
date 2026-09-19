import { describe, expect, it } from 'vitest'
import type { DailyLog, EventKind, TimelineEvent } from '../../types/api'
import { buildItineraryDays, carriedLabel } from './itinerary'

const place = { lat: 0, lon: 0, name: 'Boise, ID' }
const ev = (id: string, kind: EventKind, label: string, start: string, end: string): TimelineEvent => ({
  id,
  kind,
  status: kind === 'drive' ? 'D' : kind === 'restart' ? 'OFF' : kind === 'rest' ? 'SB' : 'ON',
  label,
  start,
  end,
  duration_hours: 0,
  miles: 0,
  start_mile: 0,
  end_mile: 0,
  leg_index: 1,
  start_location: place,
  end_location: place,
})
const log = (date: string, day_number: number) => ({ date, day_number }) as DailyLog

// Seattle -> Houston shape: a restart from Day 1 16:30 to Day 3 02:30 leaves Day 2 empty.
const timeline = [
  ev('e1', 'drive', 'Driving', '2026-09-21T06:30', '2026-09-21T16:30'),
  ev('e2', 'restart', '34-hour restart', '2026-09-21T16:30', '2026-09-23T02:30'),
  ev('e3', 'pre_trip', 'Pre-trip inspection', '2026-09-23T02:30', '2026-09-23T03:00'),
  ev('e4', 'rest', '10-hour rest (sleeper berth)', '2026-09-23T14:45', '2026-09-24T00:45'),
  ev('e5', 'drive', 'Driving', '2026-09-24T01:15', '2026-09-24T03:00'),
]
const logs = ['2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24'].map((d, i) => log(d, i + 1))

describe('buildItineraryDays', () => {
  const days = buildItineraryDays(timeline, logs)

  it('has one group per log sheet, including a day with no events', () => {
    expect(days.map((d) => [d.date, d.log?.day_number, d.events.map((e) => e.id)])).toEqual([
      ['2026-09-21', 1, ['e1', 'e2']],
      ['2026-09-22', 2, []],
      ['2026-09-23', 3, ['e3', 'e4']],
      ['2026-09-24', 4, ['e5']],
    ])
  })

  it('carries a restart or rest that runs through midnight into the next day', () => {
    expect(days[0].carried).toBeNull()
    expect(carriedLabel(days[1].carried!)).toBe('34-hour restart continues (off duty all day)')
    expect(carriedLabel(days[2].carried!)).toBe('34-hour restart continues until 02:30')
    expect(carriedLabel(days[3].carried!)).toBe('10-hour rest continues until 00:45')
  })

  it('still shows days that have events but no sheet', () => {
    expect(buildItineraryDays(timeline, []).map((d) => d.date)).toEqual(['2026-09-21', '2026-09-23', '2026-09-24'])
  })
})
