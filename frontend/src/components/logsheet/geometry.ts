// Pure geometry and formatting helpers for the FMCSA daily log sheet.
// Everything here is framework-free so it can be unit-tested and reused
// (SVG rendering, exports, legends) without touching the DOM.

import { placeLabel } from '../../lib/format'
import type { DailyLog, DutyStatus, LogRemark, LogSegment } from '../../types/api'

export const MINUTES_PER_DAY = 1440

/** Sheet canvas (SVG user units). Landscape, roughly US-letter proportions. */
export const SHEET = { width: 1100, height: 850 } as const

/** The 24-hour graph grid and the rulers/columns that hang off it. */
export const GRID = {
  labelX: 40, // left edge of the row-label column
  left: 160, // x of midnight (00:00)
  right: 1000, // x of midnight (24:00)
  barTop: 262, // black hour-label bar
  barHeight: 24,
  rowHeight: 36,
  totalsLeft: 1010, // "Total Hours" column
  totalsRight: 1060,
} as const

export const GRID_TOP = GRID.barTop + GRID.barHeight
export const GRID_BOTTOM = GRID_TOP + GRID.rowHeight * 4
export const PX_PER_HOUR = (GRID.right - GRID.left) / 24

/** Second ruler under the grid, labelled REMARKS (as on the FMCSA form). */
export const REMARKS = {
  labelY: GRID_BOTTOM + 15, // repeated hour labels
  rulerTop: GRID_BOTTOM + 19,
  rulerBottom: GRID_BOTTOM + 37,
  bracketTop: GRID_BOTTOM + 42,
  bracketDepth: 9,
  // y where rotated labels start: low enough that a leader's horizontal run (just under the
  // brackets) clears the ascenders of the label before it (~0.75 * fontSize * cos 45°).
  textTop: GRID_BOTTOM + 68,
  bottom: 664, // labels must end above this line
  rightLimit: SHEET.width - 16, // labels must end left of this x
} as const

/** Grid row order, top to bottom, as printed on the form. */
export const STATUS_ORDER: readonly DutyStatus[] = ['OFF', 'SB', 'D', 'ON']

export const STATUS_LABELS: Record<DutyStatus, string> = {
  OFF: 'Off Duty',
  SB: 'Sleeper Berth',
  D: 'Driving',
  ON: 'On Duty (not driving)',
}

const clampMinute = (m: number) => Math.min(MINUTES_PER_DAY, Math.max(0, m))

/** Minute of the day (0..1440, fractional allowed) to grid x. Not snapped. */
export function minuteToX(minute: number): number {
  return GRID.left + (clampMinute(minute) / MINUTES_PER_DAY) * (GRID.right - GRID.left)
}

/** Top edge of a status row. */
export function statusRowTop(status: DutyStatus): number {
  return GRID_TOP + STATUS_ORDER.indexOf(status) * GRID.rowHeight
}

/** Vertical centre of a status row: where the duty line runs. */
export function statusToRowY(status: DutyStatus): number {
  return statusRowTop(status) + GRID.rowHeight / 2
}

/** Sorted, clamped copy with zero-length pieces dropped and same-status neighbours merged. */
export function normalizeSegments(segments: readonly LogSegment[]): LogSegment[] {
  const sorted = segments
    .map((s) => ({
      status: s.status,
      start_minute: clampMinute(s.start_minute),
      end_minute: clampMinute(s.end_minute),
    }))
    .filter((s) => s.end_minute > s.start_minute)
    .sort((a, b) => a.start_minute - b.start_minute)

  const merged: LogSegment[] = []
  for (const seg of sorted) {
    const prev = merged[merged.length - 1]
    if (prev && prev.status === seg.status && seg.start_minute <= prev.end_minute) {
      prev.end_minute = Math.max(prev.end_minute, seg.end_minute)
    } else {
      merged.push({ ...seg })
    }
  }
  return merged
}

const r = (n: number) => Math.round(n * 100) / 100

/**
 * The continuous "pen" line: horizontal runs at row centres joined by vertical
 * connectors at every status change. A gap in the data lifts the pen (new `M`).
 */
export function buildDutyPath(segments: readonly LogSegment[]): string {
  const segs = normalizeSegments(segments)
  const parts: string[] = []
  let penX: number | null = null
  let penY: number | null = null
  for (const seg of segs) {
    const x1 = minuteToX(seg.start_minute)
    const x2 = minuteToX(seg.end_minute)
    const y = statusToRowY(seg.status)
    if (penX === null || Math.abs(penX - x1) > 0.01) {
      parts.push(`M${r(x1)} ${r(y)}`)
    } else if (penY !== y) {
      parts.push(`V${r(y)}`)
    }
    parts.push(`H${r(x2)}`)
    penX = x2
    penY = y
  }
  return parts.join(' ')
}

/** Cup-shaped bracket under a remark's time span (FMCSA p.18-19 style). */
export function bracketPath(startMinute: number, endMinute: number): string {
  let x1 = minuteToX(startMinute)
  let x2 = minuteToX(endMinute)
  // Keep 1-5 minute stops visible, and leave a hairline between adjacent cups.
  const minWidth = 4
  if (x2 - x1 < minWidth) {
    const mid = (x1 + x2) / 2
    x1 = mid - minWidth / 2
    x2 = mid + minWidth / 2
  } else {
    x1 += 0.75
    x2 -= 0.75
  }
  const top = REMARKS.bracketTop
  const bottom = top + REMARKS.bracketDepth
  return `M${r(x1)} ${top} V${bottom} H${r(x2)} V${top}`
}

/** A zero-length remark: the trip's first change from off duty or its last change back to it. */
export function isFlag(remark: Pick<LogRemark, 'start_minute' | 'end_minute'>): boolean {
  return remark.end_minute <= remark.start_minute
}

/** Size of a flag's 45-degree tick, in SVG units along each axis. */
export const FLAG_TICK = 6

/**
 * Flag for a change of duty status at one instant (as drivers mark it on paper): a stem from
 * the remarks ruler down to the bracket line, then a short 45-degree tick parallel to the labels.
 */
export function flagPath(minute: number): string {
  const x = r(minuteToX(minute))
  const bottom = REMARKS.bracketTop + REMARKS.bracketDepth
  return `M${x} ${REMARKS.rulerBottom} V${bottom} l${FLAG_TICK} ${FLAG_TICK}`
}

/** The mark under a remark on the ruler: a flag for an instant, else a bracket over its span. */
export function remarkMarkPath(remark: Pick<LogRemark, 'start_minute' | 'end_minute'>): string {
  return isFlag(remark) ? flagPath(remark.start_minute) : bracketPath(remark.start_minute, remark.end_minute)
}

// ---------- Totals ----------

export type StatusMinutes = Record<DutyStatus, number>

export function minutesByStatus(segments: readonly LogSegment[]): StatusMinutes {
  const out: StatusMinutes = { OFF: 0, SB: 0, D: 0, ON: 0 }
  for (const s of normalizeSegments(segments)) out[s.status] += s.end_minute - s.start_minute
  return out
}

/**
 * Whole minutes per status with the largest-remainder method, so the printed row
 * totals always add up exactly to the printed grand total (24:00 for a full day),
 * even when segment boundaries fall on fractional minutes.
 */
export function roundedMinutesByStatus(minutes: StatusMinutes): StatusMinutes {
  const exact = STATUS_ORDER.map((s) => minutes[s])
  const floors = exact.map(Math.floor)
  let deficit = Math.round(exact.reduce((a, b) => a + b, 0)) - floors.reduce((a, b) => a + b, 0)
  const order = exact.map((m, i) => ({ i, rem: m - floors[i] })).sort((a, b) => b.rem - a.rem)
  for (const { i } of order) {
    if (deficit <= 0) break
    floors[i] += 1
    deficit -= 1
  }
  const out: StatusMinutes = { OFF: 0, SB: 0, D: 0, ON: 0 }
  STATUS_ORDER.forEach((s, i) => (out[s] = floors[i]))
  return out
}

// ---------- Text ----------

/** Truncate to `max` characters with a trailing ellipsis. */
export function truncate(text: string, max: number): string {
  const t = text.trim()
  if (max <= 0) return ''
  if (t.length <= max) return t
  if (max === 1) return '…'
  return `${t.slice(0, max - 1).trimEnd()}…`
}

/** The full "City, ST — Note" label. Remarks are never truncated: long ones wrap or shrink. */
export function remarkText(remark: Pick<LogRemark, 'location' | 'note'>): string {
  const location = (remark.location || '').trim()
  const note = (remark.note || '').trim()
  return location && note ? `${location} — ${note}` : location || note
}

// ---------- Remark label layout ----------

/** Approximate advance width of one monospace glyph, as a fraction of font size. */
export const MONO_CHAR_WIDTH = 0.6

/** Remarks at the same place starting within this many minutes share one label. */
export const REMARK_MERGE_MINUTES = 60

/** One written remark: one or more consecutive duty changes at the same place. */
export interface RemarkGroup {
  start_minute: number
  end_minute: number
  /**
   * Where it happened, as FMCSA p.17 asks: the city and state, and outside a city the highway
   * too ("I-70 near Chapman, KS"). One form for the whole group.
   */
  location: string
  /** City/state key the group was merged on ("Chapman, KS"). */
  place: string
  /** Activities in time order, in paper-log shorthand, e.g. "Post-trip / 10-h rest (SB)". */
  note: string
  /** The remarks this label covers; each still gets its own bracket (or flag). */
  members: LogRemark[]
}

/**
 * Sort remarks and merge consecutive ones at the same place that start close together,
 * as a driver would write "Joplin, MO — Post-trip / 10-h rest (SB)" once instead of
 * squeezing two labels into a few pixels.
 */
export function groupRemarks(remarks: readonly LogRemark[]): RemarkGroup[] {
  const sorted = [...remarks]
    .filter((rm) => Number.isFinite(rm.start_minute))
    .sort((a, b) => a.start_minute - b.start_minute || a.end_minute - b.end_minute)
  const groups: RemarkGroup[] = []
  for (const rm of sorted) {
    const place = placeLabel(rm.location, { withRoad: false })
    const location = placeLabel(rm.location)
    const note = shortNote(rm.note, rm.status)
    const prev = groups[groups.length - 1]
    const last = prev?.members[prev.members.length - 1]
    if (prev && last && prev.place === place && rm.start_minute - last.start_minute <= REMARK_MERGE_MINUTES) {
      prev.members.push(rm)
      prev.end_minute = Math.max(prev.end_minute, rm.end_minute)
      // "Joplin, MO" then "I-44 near Joplin, MO": keep the form that names the highway.
      if (location.length > prev.location.length) prev.location = location
      if (note && !prev.note.split(' / ').includes(note)) prev.note = prev.note ? `${prev.note} / ${note}` : note
    } else {
      groups.push({ start_minute: rm.start_minute, end_minute: rm.end_minute, location, place, note, members: [rm] })
    }
  }
  return groups
}

/**
 * Paper-log shorthand for an activity: "Post-trip inspection" -> "Post-trip",
 * "10-hour rest" (sleeper) -> "10-h rest (SB)", "10-hour rest (cont.)" -> "10-h rest (SB, cont.)".
 */
export function shortNote(note: string, status?: DutyStatus): string {
  let s = note
    .trim()
    .replace(/\b(Pre|Post)-trip inspection\b/gi, '$1-trip')
    .replace(/\b(\d+)-hours?\b/gi, '$1-h')
    .replace(/\b(\d+)-minutes?\b/gi, '$1-min')
    .replace(/\s*\(sleeper berth\)/i, ' (SB)')
    .replace(/\s*\(off duty\)/i, ' (OFF)')
  // A 10-hour rest can be logged either way, so the sheet says which.
  if (/\brest\b/i.test(s) && !/\brestart\b/i.test(s) && (status === 'SB' || status === 'OFF') && !/\((SB|OFF)\b/.test(s)) {
    const cont = /\s*\(cont\.\)/i.test(s)
    s = `${s.replace(/\s*\(cont\.\)/i, '')} (${status}${cont ? ', cont.' : ''})`
  }
  return s
}

export interface RemarkLayout {
  group: RemarkGroup
  /** Bracket start on the ruler. */
  startX: number
  /** Where the rotated label is anchored (may be pushed right of startX). */
  anchorX: number
  anchorY: number
  /** The whole label, never truncated. */
  text: string
  /** One line, or two ("City, ST" / activity) when one would not fit. */
  lines: string[]
  /** Font size for this label: shrunk when needed, never below REMARK_MIN_FONT. */
  fontSize: number
  /** Baseline-to-baseline distance between the two lines. */
  lineHeight: number
  /** True when the label was moved off its bracket and needs a leader line. */
  displaced: boolean
}

export interface RemarkLayoutOptions {
  fontSize?: number
  /** Smallest size a one-line label may shrink to before it wraps onto two lines. */
  minFontSize?: number
  /** Rotation of the labels in degrees (positive = clockwise in SVG). */
  angle?: number
}

/** Absolute floor for a label that is still too long on two lines. */
export const REMARK_MIN_FONT = 6.5

/**
 * Lay out diagonal remark labels without overlap and without truncation.
 *
 * All labels share one rotation, so they are parallel strips. Two strips whose anchors sit on
 * the same baseline are separated perpendicularly by dx * sin(angle); they never collide if
 * that separation covers the right label's descent (plus its second line, if wrapped) and the
 * left label's ascent, regardless of text length. That reduces the problem to 1-D spacing of
 * anchors along the baseline: a forward pass pushes crowded labels right, and a backward pass
 * pulls them back inside the right limit. A label that does not fit on one line at
 * `minFontSize` wraps to "City, ST" over the activity; the layout then runs once more with the
 * wider spacing that needs. Finally each label shrinks to the room it has.
 */
export function layoutRemarks(remarks: readonly LogRemark[], opts: RemarkLayoutOptions = {}): RemarkLayout[] {
  const fontSize = opts.fontSize ?? 10.5
  const angle = ((opts.angle ?? 45) * Math.PI) / 180
  const sin = Math.sin(angle)
  const cos = Math.cos(angle)
  const minFontSize = Math.min(fontSize, opts.minFontSize ?? 8.5)
  const lineHeight = fontSize * 1.15
  const ascent = fontSize * 0.75
  const minX = GRID.left + 2
  const maxX = GRID.right + 30
  const anchorY = REMARKS.textTop

  const groups = groupRemarks(remarks)
  const n = groups.length
  if (n === 0) return []

  const texts = groups.map((g) => remarkText(g))
  const wrapped = groups.map((g) => [g.location, g.note].filter(Boolean))
  const width = (lines: string[], size: number) => Math.max(...lines.map((l) => l.length)) * size * MONO_CHAR_WIDTH
  // Room along the text before the sheet's bottom and right edges, for a label anchored at x.
  const roomY = (lineCount: number) => (REMARKS.bottom - anchorY - (lineCount - 1) * lineHeight * cos) / sin
  const roomX = (x: number) => (REMARKS.rightLimit - x - ascent * sin) / cos
  const room = (x: number, lineCount: number) => Math.min(roomX(x), roomY(lineCount))

  // Start on one line unless even the full height of the remarks area cannot hold it.
  let lines = groups.map((_, i) => (width([texts[i]], minFontSize) > roomY(1) && wrapped[i].length > 1 ? wrapped[i] : [texts[i]]))
  const ideal = groups.map((g) => minuteToX(g.start_minute) + 3)
  let anchors = [...ideal]

  for (let pass = 0; pass < 3; pass++) {
    // gaps[i]: baseline distance needed between label i-1 and label i.
    let gaps = lines.map((ls) => (fontSize * 1.3 + (ls.length - 1) * lineHeight) / sin)
    const needed = gaps.slice(1).reduce((a, b) => a + b, 0)
    // Shrink the gaps if a pathological number of remarks would not otherwise fit.
    if (needed > maxX - minX) gaps = gaps.map((g) => (g * (maxX - minX)) / needed)

    // Near midnight a label would run off the sheet: let it slide left (with a leader line)
    // far enough to fit, but not absurdly far from its bracket.
    const labelRun = (i: number) => Math.min(width(lines[i], fontSize), roomY(lines[i].length)) * cos + ascent * sin
    const caps = groups.map((_, i) => Math.min(maxX, Math.max(REMARKS.rightLimit - labelRun(i), ideal[i] - 200)))
    anchors = [...ideal]
    for (let i = 0; i < n; i++) anchors[i] = Math.max(anchors[i], minX, i > 0 ? anchors[i - 1] + gaps[i] : -Infinity)
    for (let i = n - 1; i >= 0; i--) anchors[i] = Math.min(anchors[i], caps[i], i < n - 1 ? anchors[i + 1] - gaps[i + 1] : Infinity)
    for (let i = 0; i < n; i++) anchors[i] = Math.max(anchors[i], minX, i > 0 ? anchors[i - 1] + gaps[i] : -Infinity)

    const next = lines.map((ls, i) =>
      ls.length === 1 && wrapped[i].length > 1 && width(ls, minFontSize) > room(anchors[i], 1) ? wrapped[i] : ls,
    )
    if (next.every((ls, i) => ls === lines[i])) break
    lines = next
  }

  return groups.map((group, i) => {
    const anchorX = anchors[i]
    const fit = room(anchorX, lines[i].length) / (width(lines[i], 1) || 1)
    const size = Math.max(REMARK_MIN_FONT, Math.min(fontSize, fit))
    return {
      group,
      startX: minuteToX(group.start_minute),
      anchorX,
      anchorY,
      text: texts[i],
      lines: lines[i],
      fontSize: Math.floor(size * 10) / 10,
      lineHeight,
      displaced: Math.abs(anchorX - ideal[i]) > 1.5,
    }
  })
}

/**
 * Dashed leader from a displaced label's bracket to its anchor. It drops just below the
 * brackets, runs horizontally above the label strips, then angles into the anchor, so it
 * never cuts through the label written before it.
 */
export function leaderPoints(layout: Pick<RemarkLayout, 'startX' | 'anchorX' | 'anchorY'>): Array<[number, number]> {
  const y = REMARKS.bracketTop + REMARKS.bracketDepth + 3
  return [
    [layout.startX, REMARKS.bracketTop + REMARKS.bracketDepth],
    [layout.startX, y],
    [layout.anchorX - 6, y],
    [layout.anchorX - 1, layout.anchorY - 1],
  ]
}

export function leaderPath(layout: Pick<RemarkLayout, 'startX' | 'anchorX' | 'anchorY'>): string {
  return leaderPoints(layout)
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${r(x)} ${r(y)}`)
    .join(' ')
}

/**
 * Corners of a rotated label's box (baseline anchor, clockwise angle): from the
 * descenders to the ascenders, along the text's advance. Used by tests and debug views.
 */
export function labelCorners(layout: RemarkLayout, angleDeg = 45): Array<[number, number]> {
  const a = (angleDeg * Math.PI) / 180
  const ux = Math.cos(a)
  const uy = Math.sin(a) // along the text
  const nx = Math.sin(a)
  const ny = -Math.cos(a) // "up" from the baseline
  const len = Math.max(...layout.lines.map((l) => l.length)) * layout.fontSize * MONO_CHAR_WIDTH
  const up = layout.fontSize * 0.75
  const down = layout.fontSize * 0.25 + (layout.lines.length - 1) * layout.lineHeight
  const p = (t: number, h: number): [number, number] => [layout.anchorX + ux * t + nx * h, layout.anchorY + uy * t + ny * h]
  return [p(0, -down), p(len, -down), p(len, up), p(0, up)]
}

// ---------- Misc ----------

/** "2026-09-19" -> { month: "09", day: "19", year: "2026" } without timezone drift. */
export function splitDate(iso: string): { month: string; day: string; year: string } {
  const [year = '', month = '', day = ''] = iso.split('-')
  return { month, day, year }
}

/** Short weekday + M/D for pills, parsed as a local calendar date. */
export function shortDateLabel(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return iso
  const date = new Date(y, m - 1, d)
  const wd = date.toLocaleDateString('en-US', { weekday: 'short' })
  return `${wd} ${m}/${d}`
}

/**
 * 34-hour restart state for the recap: 'completed' when a restart ends on this
 * sheet, 'in-progress' when one runs through midnight, otherwise null.
 *
 * A restart that ends exactly at 24:00 has also completed: the cycle resets on this
 * sheet (A = 0). A sheet in the middle of a restart can never show 0 used, because a
 * restart is only scheduled when the cycle is nearly spent.
 */
export function restartState(remarks: readonly LogRemark[], cycleUsed: number): 'completed' | 'in-progress' | null {
  const restarts = remarks.filter((rm) => /34[\s-]*(h|hr|hour)|restart/i.test(rm.note))
  if (restarts.length === 0) return null
  const done = restarts.some((rm) => rm.end_minute < MINUTES_PER_DAY || (rm.end_minute >= MINUTES_PER_DAY && cycleUsed === 0))
  return done ? 'completed' : 'in-progress'
}

/**
 * Recap values for the 70-hour/8-day block. The API gives cycle hours used (carried-in hours
 * included, no roll-off) but no per-day history for the carried-in hours, so A (last 7 days)
 * and C (last 8 days) both show that conservative total; B = 70 - A.
 */
export function recapValues(log: Pick<DailyLog, 'segments' | 'cycle_hours_used'>): {
  onDutyTodayMinutes: number
  a: number
  b: number
  c: number
} {
  const rounded = roundedMinutesByStatus(minutesByStatus(log.segments))
  const used = Math.max(0, log.cycle_hours_used)
  return { onDutyTodayMinutes: rounded.D + rounded.ON, a: used, b: Math.max(0, 70 - used), c: used }
}

/**
 * The header has one free-text shipping field. "Pro No. 101601 · General freight" splits at
 * the "·" into the manifest line and the shipper & commodity line. Otherwise a code-like
 * value (no spaces or mostly digits, e.g. "BOL-10442") goes on the manifest line and prose
 * such as "Acme Foods, frozen produce" on the shipper & commodity line.
 */
export function splitShippingDoc(raw: string): { manifest: string; shipper: string } {
  const value = raw.trim()
  if (!value) return { manifest: '', shipper: '' }
  const parts = value.split('·').map((p) => p.trim())
  if (parts.length === 2 && parts[0] && parts[1]) return { manifest: parts[0], shipper: parts[1] }
  const digits = value.replace(/\D/g, '').length
  const looksLikeNumber = !/\s/.test(value) || digits / value.length >= 0.5
  return looksLikeNumber ? { manifest: value, shipper: '' } : { manifest: '', shipper: value }
}
