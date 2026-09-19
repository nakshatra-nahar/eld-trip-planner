import { describe, expect, it } from 'vitest'
import type { EventKind, TimelineEvent } from '../types/api'
import { drivingByDutyPeriod, dutyPeriodNote } from './dutyPeriods'

const place = { lat: 0, lon: 0, name: 'Tulsa, OK' }
const ev = (kind: EventKind, start: string, end: string): TimelineEvent => ({
  id: `${kind}-${start}`,
  kind,
  status: kind === 'drive' ? 'D' : kind === 'rest' ? 'SB' : kind === 'restart' ? 'OFF' : 'ON',
  label: kind,
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

// Period 1 drives 11:00 on Sep 21 (00:00-11:00); a 10-hour rest; period 2 drives 1:15 before midnight.
const twoPeriods = [
  ev('drive', '2026-09-20T22:00', '2026-09-21T11:00'),
  ev('rest', '2026-09-21T11:15', '2026-09-21T21:15'),
  ev('pre_trip', '2026-09-21T21:15', '2026-09-21T21:45'),
  ev('drive', '2026-09-21T21:45', '2026-09-21T23:00'),
  ev('fuel', '2026-09-21T23:00', '2026-09-21T23:30'),
  ev('drive', '2026-09-21T23:30', '2026-09-22T05:00'),
]

describe('drivingByDutyPeriod', () => {
  it('clips driving to the calendar day and splits it at rests', () => {
    expect(drivingByDutyPeriod(twoPeriods, '2026-09-21')).toEqual([660, 105])
    expect(drivingByDutyPeriod(twoPeriods, '2026-09-20')).toEqual([120])
    expect(drivingByDutyPeriod(twoPeriods, '2026-09-22')).toEqual([300])
  })

  it('treats a 34-hour restart as a duty-period boundary too', () => {
    const t = [ev('drive', '2026-09-21T00:00', '2026-09-21T02:00'), ev('restart', '2026-09-21T02:00', '2026-09-21T12:00'), ev('drive', '2026-09-21T12:00', '2026-09-21T13:00')]
    expect(drivingByDutyPeriod(t, '2026-09-21')).toEqual([120, 60])
  })
})

describe('dutyPeriodNote', () => {
  it('explains a day with more than 11:00 of driving across two duty periods', () => {
    expect(dutyPeriodNote(twoPeriods, '2026-09-21')).toBe('2 duty periods today: 11:00 + 1:45 driving; each ≤ 11 h (§395.3)')
  })

  it('stays silent at or under 11:00, or with a single duty period', () => {
    const exactly11 = [ev('drive', '2026-09-21T00:00', '2026-09-21T05:00'), ev('rest', '2026-09-21T05:00', '2026-09-21T15:00'), ev('drive', '2026-09-21T15:00', '2026-09-21T21:00')]
    expect(dutyPeriodNote(exactly11, '2026-09-21')).toBeNull()
    expect(dutyPeriodNote(twoPeriods, '2026-09-22')).toBeNull()
  })
})
