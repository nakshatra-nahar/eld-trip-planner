// Formatting helpers. API times are zone-less "YYYY-MM-DDTHH:MM" home-terminal wall-clock strings.
// They are parsed as if they were UTC and always formatted with timeZone 'UTC', so the viewer's own
// time zone and DST never shift or distort them.

const pad = (n: number) => String(n).padStart(2, '0')

export function parseWallTime(value: string): Date {
  const [date, time = '00:00'] = value.split('T')
  const [y, m, d] = date.split('-').map(Number)
  const [hh, mm] = time.split(':').map(Number)
  return new Date(Date.UTC(y, m - 1, d, hh, mm))
}

/** The next full hour in the viewer's local time, as a datetime-local value. */
export function nextFullHour(now = new Date()): string {
  const d = new Date(now)
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`
}

export function isValidWallTime(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return false
  return !Number.isNaN(parseWallTime(value).getTime())
}

/** "14:30" (24-hour clock, as on ELD displays). */
export function formatClock(value: string): string {
  return value.slice(11, 16)
}

const dayFmt = new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })
const dayLongFmt = new Intl.DateTimeFormat('en-US', {
  weekday: 'long',
  month: 'long',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
})

/** "Mon, Sep 21" */
export function formatDay(value: string): string {
  return dayFmt.format(parseWallTime(value.length === 10 ? `${value}T00:00` : value))
}

export function formatDayLong(value: string): string {
  return dayLongFmt.format(parseWallTime(value.length === 10 ? `${value}T00:00` : value))
}

const monthDayFmt = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })

/** "Sep 21, 06:00": fits a narrow card on one line. */
export function formatShortDateTime(value: string): string {
  return `${monthDayFmt.format(parseWallTime(value))}, ${formatClock(value)}`
}

/** "Mon, Sep 21 · 06:00" */
export function formatDateTime(value: string): string {
  return `${formatDay(value)} · ${formatClock(value)}`
}

/** Hours -> "10h 15m", "45m", or "3d 0h 58m" when `days` is set and span exceeds 24 h. */
export function formatDuration(hours: number, { days = false } = {}): string {
  const total = Math.max(0, Math.round(hours * 60))
  const d = days ? Math.floor(total / 1440) : 0
  const h = Math.floor((total - d * 1440) / 60)
  const m = total % 60
  if (d > 0) return `${d}d ${h}h ${pad(m)}m`
  if (h === 0) return `${m}m`
  return m === 0 ? `${h}h` : `${h}h ${pad(m)}m`
}

const intFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const oneFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1, minimumFractionDigits: 1 })

export function formatMiles(miles: number, { unit = true } = {}): string {
  const value = miles < 10 ? oneFmt.format(miles) : intFmt.format(miles)
  return unit ? `${value} mi` : value
}

/**
 * Hours as an hh:mm clock span, the way ELD printouts show totals: 22.1667 -> "22:10",
 * 0.5833 -> "0:35". Used on the log sheet (Total Hours column and Recap).
 */
export function formatHoursClock(hours: number): string {
  return formatMinutesClock(Math.round(hours * 60))
}

/** Whole minutes as "h:mm", e.g. 1440 -> "24:00". */
export function formatMinutesClock(minutes: number): string {
  const total = Math.max(0, Math.round(minutes))
  return `${Math.floor(total / 60)}:${pad(total % 60)}`
}

/** "I 84 near Joliet, IL" -> "Joliet, IL"; other names are returned unchanged. */
export function withoutRoad(location: string): string {
  const m = /^.+?\snear\s+(.+)$/i.exec(location || '')
  return m ? m[1] : location
}

/**
 * One display form for every place name in the app (overview, itinerary, map, logs):
 * "Saint Louis, MO" and "St. Louis, MO" both become "St. Louis, MO", and interstates are
 * written the way drivers read them ("I 44" -> "I-44"). With `withRoad: false` the
 * "I-44 near" prefix is dropped, leaving the city/state an FMCSA remark needs.
 */
export function placeLabel(name: string, { withRoad = true }: { withRoad?: boolean } = {}): string {
  let s = (name || '').trim().replace(/\s+/g, ' ')
  if (!withRoad) s = withoutRoad(s)
  return s.replace(/\bSaint\s+(?=[A-Z])/g, 'St. ').replace(/\bI[\s-]?(\d{1,3})\b/g, 'I-$1')
}

/** Minutes between two wall-clock strings. */
export function minutesBetween(start: string, end: string): number {
  return Math.round((parseWallTime(end).getTime() - parseWallTime(start).getTime()) / 60000)
}
