import { describe, expect, it } from 'vitest'
import { homeClock, localTimeNote, outsideDockHours } from './localTime'

describe('localTimeNote', () => {
  it('shows the local time only when it differs from home-terminal time', () => {
    expect(localTimeNote('2026-09-21T18:14', '2026-09-21T19:14', 'EDT')).toBe('19:14 EDT local')
    expect(localTimeNote('2026-09-21T18:14', '2026-09-21T18:14', 'CDT')).toBeNull()
    expect(localTimeNote('2026-09-21T18:14', undefined, 'CDT')).toBeNull()
  })
  it('formats the home clock with its zone', () => {
    expect(homeClock('2026-09-21T18:14', 'CDT')).toBe('18:14 CDT')
    expect(homeClock('2026-09-21T18:14')).toBe('18:14')
  })
})

describe('outsideDockHours', () => {
  it.each([
    ['2026-09-21T21:59', false],
    ['2026-09-21T22:00', true],
    ['2026-09-22T03:37', true],
    ['2026-09-22T04:59', true],
    ['2026-09-22T05:00', false],
    ['2026-09-22T12:00', false],
  ])('%s -> %s', (t, out) => expect(outsideDockHours(t)).toBe(out))
})
