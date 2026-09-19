import { describe, expect, it } from 'vitest'
import { formatDuration, formatHoursClock, formatMinutesClock, placeLabel } from './format'

describe('formatDuration', () => {
  it.each([
    [0, '0m'],
    [0.5833, '35m'],
    [1, '1h'],
    [17.3333, '17h 20m'],
    [39.1667, '39h 10m'],
    [70, '70h'],
    [-2, '0m'],
  ])('%s h -> %s', (hours, text) => expect(formatDuration(hours)).toBe(text))

  it('adds days when asked', () => expect(formatDuration(49.5, { days: true })).toBe('2d 1h 30m'))
})

describe('clock totals', () => {
  it('formats minutes and hours as h:mm', () => {
    expect(formatMinutesClock(1440)).toBe('24:00')
    expect(formatMinutesClock(35)).toBe('0:35')
    expect(formatHoursClock(22.1667)).toBe('22:10')
    expect(formatHoursClock(0.5833)).toBe('0:35')
  })
})

describe('placeLabel', () => {
  it('uses one spelling for Saint/St. and hyphenates interstates', () => {
    expect(placeLabel('Saint Louis, MO')).toBe('St. Louis, MO')
    expect(placeLabel('St. Louis, MO')).toBe('St. Louis, MO')
    expect(placeLabel('I 44 near Joplin, MO')).toBe('I-44 near Joplin, MO')
  })
  it('drops the road for remarks', () => {
    expect(placeLabel('I 80 near Garrettsville, OH', { withRoad: false })).toBe('Garrettsville, OH')
    expect(placeLabel('Garrettsville, OH', { withRoad: false })).toBe('Garrettsville, OH')
  })
})
