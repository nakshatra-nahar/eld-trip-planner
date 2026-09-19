// Pure geometry and formatting helpers for the FMCSA daily log sheet.
// Everything here is framework-free so it can be unit-tested and reused
// (SVG rendering, exports, legends) without touching the DOM.

import type { DutyStatus, LogRemark, LogSegment } from '../../types/api'

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
  textTop: GRID_BOTTOM + 60, // y where rotated labels start
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

// ---------- Totals ----------

export type StatusMinutes = Record<DutyStatus, number>

export function minutesByStatus(segments: readonly LogSegment[]): StatusMinutes {
  const out: StatusMinutes = { OFF: 0, SB: 0, D: 0, ON: 0 }
  for (const s of normalizeSegments(segments)) out[s.status] += s.end_minute - s.start_minute
  return out
}

/**
 * Hours per status rounded to 0.01 h with the largest-remainder method, so the
 * printed row totals always add up exactly to the printed grand total (24 for a
 * full day), even with minute-precision segments.
 */
export function roundedHoursByStatus(minutes: StatusMinutes): Record<DutyStatus, number> {
  const hundredths = STATUS_ORDER.map((s) => (minutes[s] / 60) * 100)
  const floors = hundredths.map(Math.floor)
  const target = Math.round(hundredths.reduce((a, b) => a + b, 0))
  let deficit = target - floors.reduce((a, b) => a + b, 0)
  const order = hundredths
    .map((h, i) => ({ i, rem: h - floors[i] }))
    .sort((a, b) => b.rem - a.rem)
  for (const { i } of order) {
    if (deficit <= 0) break
    floors[i] += 1
    deficit -= 1
  }
  const out = { OFF: 0, SB: 0, D: 0, ON: 0 } as Record<DutyStatus, number>
  STATUS_ORDER.forEach((s, i) => (out[s] = floors[i] / 100))
  return out
}

/** Decimal hours as written on the FMCSA sample: "10", "4.5", "1.75", "0.08". */
export function formatHours(hours: number): string {
  const fixed = (Math.round(hours * 100) / 100).toFixed(2)
  return fixed.replace(/\.?0+$/, '')
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

/** "I 84 near Joliet, IL" -> "Joliet, IL"; other names are returned unchanged. */
export function withoutRoad(location: string): string {
  const m = /^.+?\snear\s+(.+)$/i.exec(location || '')
  return m ? m[1] : location
}

/** "City, ST — Note", keeping the city legible when the whole thing is too long. */
export function remarkText(remark: Pick<LogRemark, 'location' | 'note'>, maxChars: number): string {
  const location = truncate(remark.location || '', 32)
  const note = (remark.note || '').trim()
  const full = location && note ? `${location} — ${note}` : location || note
  return truncate(full, maxChars)
}

// ---------- Remark label layout ----------

/** Approximate advance width of one monospace glyph, as a fraction of font size. */
export const MONO_CHAR_WIDTH = 0.6

export interface RemarkLayout {
  remark: LogRemark
  /** Bracket start on the ruler. */
  startX: number
  /** Where the rotated label is anchored (may be pushed right of startX). */
  anchorX: number
  anchorY: number
  /** Label already truncated to the space available. */
  text: string
  /** Font size for this label: shrunk (down to a floor) before truncating. */
  fontSize: number
  /** True when the label was moved off its bracket and needs a leader line. */
  displaced: boolean
}

export interface RemarkLayoutOptions {
  fontSize?: number
  /** Smallest size a long label may shrink to before it is truncated. */
  minFontSize?: number
  /** Rotation of the labels in degrees (positive = clockwise in SVG). */
  angle?: number
}

/**
 * Lay out diagonal remark labels without overlap.
 *
 * All labels share one rotation, so they are parallel strips. Two strips whose
 * anchors sit on the same baseline are separated perpendicularly by
 * dx * sin(angle); they never collide if that separation is at least one line
 * height, regardless of text length. That reduces the problem to 1-D spacing of
 * anchors along the baseline: a forward pass pushes crowded labels right, a
 * backward pass pulls them back inside the right limit, and each label is then
 * truncated to the room left before the sheet's right/bottom edges.
 */
export function layoutRemarks(
  remarks: readonly LogRemark[],
  opts: RemarkLayoutOptions = {},
): RemarkLayout[] {
  const fontSize = opts.fontSize ?? 10.5
  const angle = ((opts.angle ?? 45) * Math.PI) / 180
  const sin = Math.sin(angle)
  const cos = Math.cos(angle)
  const minFontSize = Math.min(fontSize, opts.minFontSize ?? 8.5)
  const lineGap = fontSize * 1.3
  const minX = GRID.left + 2
  const maxX = GRID.right + 30

  const sorted = [...remarks]
    .filter((rm) => Number.isFinite(rm.start_minute))
    .sort((a, b) => a.start_minute - b.start_minute || a.end_minute - b.end_minute)
  const n = sorted.length
  if (n === 0) return []

  // Shrink the gap if a pathological number of remarks would not otherwise fit.
  const gap = Math.min(lineGap / sin, (maxX - minX) / Math.max(1, n - 1))

  const ideal = sorted.map((rm) => minuteToX(rm.start_minute) + 3)
  const anchors = [...ideal]
  for (let i = 0; i < n; i++) {
    anchors[i] = Math.max(anchors[i], minX, i > 0 ? anchors[i - 1] + gap : -Infinity)
  }
  // Near midnight a label would run off the sheet: let it slide left (with a
  // leader line) far enough to fit, but not absurdly far from its bracket.
  const labelRun = (rm: LogRemark) =>
    Math.min(remarkText(rm, Number.POSITIVE_INFINITY).length * fontSize * MONO_CHAR_WIDTH, (REMARKS.bottom - REMARKS.textTop) / sin) * cos
  const caps = sorted.map((rm, i) => Math.min(maxX, Math.max(REMARKS.rightLimit - labelRun(rm), ideal[i] - 200)))
  for (let i = n - 1; i >= 0; i--) {
    anchors[i] = Math.min(anchors[i], caps[i], i < n - 1 ? anchors[i + 1] - gap : Infinity)
  }
  for (let i = 0; i < n; i++) {
    anchors[i] = Math.max(anchors[i], minX, i > 0 ? anchors[i - 1] + gap : -Infinity)
  }

  const anchorY = REMARKS.textTop
  return sorted.map((remark, i) => {
    const anchorX = anchors[i]
    const roomX = (REMARKS.rightLimit - anchorX) / cos
    const roomY = (REMARKS.bottom - anchorY) / sin
    const room = Math.min(roomX, roomY)
    // If "I 84 near Mountain Home, ID — ..." is too long, drop the road prefix first (the
    // city/state is what the FMCSA remark requires), then shrink, and truncate only as a last resort.
    const fits = (rm: Pick<LogRemark, 'location' | 'note'>) =>
      remarkText(rm, Number.POSITIVE_INFINITY).length * fontSize * MONO_CHAR_WIDTH <= room
    const shown = fits(remark) ? remark : { ...remark, location: withoutRoad(remark.location) }
    const full = remarkText(shown, Number.POSITIVE_INFINITY)
    const size = Math.max(minFontSize, Math.min(fontSize, room / (Math.max(1, full.length) * MONO_CHAR_WIDTH)))
    const maxChars = Math.floor(room / (size * MONO_CHAR_WIDTH))
    return {
      remark,
      startX: minuteToX(remark.start_minute),
      anchorX,
      anchorY,
      text: remarkText(shown, maxChars),
      fontSize: Math.round(size * 10) / 10,
      displaced: Math.abs(anchorX - ideal[i]) > 1.5,
    }
  })
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
 */
export function restartState(remarks: readonly LogRemark[]): 'completed' | 'in-progress' | null {
  const restarts = remarks.filter((rm) => /34[\s-]*(h|hr|hour)|restart/i.test(rm.note))
  if (restarts.length === 0) return null
  return restarts.some((rm) => rm.end_minute < MINUTES_PER_DAY) ? 'completed' : 'in-progress'
}
