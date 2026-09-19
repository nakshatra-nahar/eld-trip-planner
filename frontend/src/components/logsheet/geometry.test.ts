import { describe, expect, it } from 'vitest'
import type { LogRemark, LogSegment } from '../../types/api'
import {
  buildDutyPath,
  groupRemarks,
  labelCorners,
  layoutRemarks,
  leaderPoints,
  minutesByStatus,
  recapValues,
  REMARK_MIN_FONT,
  REMARKS,
  restartState,
  roundedMinutesByStatus,
  shortNote,
  type RemarkLayout,
} from './geometry'

type Pt = [number, number]

/** Separating-axis test for two convex quadrilaterals. */
function polygonsIntersect(a: Pt[], b: Pt[]): boolean {
  for (const poly of [a, b]) {
    for (let i = 0; i < poly.length; i++) {
      const [x1, y1] = poly[i]
      const [x2, y2] = poly[(i + 1) % poly.length]
      const nx = y2 - y1
      const ny = x1 - x2
      const project = (p: Pt[]) => p.map(([x, y]) => x * nx + y * ny)
      const pa = project(a)
      const pb = project(b)
      if (Math.max(...pa) <= Math.min(...pb) || Math.max(...pb) <= Math.min(...pa)) return false
    }
  }
  return true
}

function segmentHitsPolygon(p: Pt, q: Pt, poly: Pt[]): boolean {
  // Treat the segment as a degenerate (zero-width) polygon.
  return polygonsIntersect([p, q, q, p], poly)
}

const remark = (start: number, end: number, location: string, note: string, status: LogRemark['status'] = 'ON'): LogRemark => ({
  start_minute: start,
  end_minute: end,
  status,
  location,
  note,
})

describe('groupRemarks', () => {
  it('merges consecutive remarks at the same place and keeps one form of the name', () => {
    const groups = groupRemarks([
      remark(450, 465, 'Joplin, MO', 'Post-trip inspection'),
      remark(465, 1065, 'I 44 near Joplin, MO', '10-hour rest', 'SB'),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0].location).toBe('Joplin, MO')
    expect(groups[0].note).toBe('Post-trip / 10-h rest (SB)')
    expect(groups[0].members).toHaveLength(2)
  })

  it('keeps remarks at different places apart', () => {
    expect(groupRemarks([remark(0, 60, 'Chicago, IL', 'Pre-trip'), remark(75, 105, 'Joliet, IL', 'Fuel')])).toHaveLength(2)
  })
})

describe('shortNote', () => {
  it.each([
    ['Pre-trip inspection', 'ON', 'Pre-trip'],
    ['10-hour rest', 'SB', '10-h rest (SB)'],
    ['10-hour rest (cont.)', 'OFF', '10-h rest (OFF, cont.)'],
    ['10-hour rest (sleeper berth)', 'SB', '10-h rest (SB)'],
    ['34-hour restart', 'OFF', '34-h restart'],
    ['30-minute break', 'OFF', '30-min break'],
    ['Fuel', 'ON', 'Fuel'],
  ] as const)('%s (%s) -> %s', (note, status, short) => expect(shortNote(note, status)).toBe(short))
})

// Remarks 15 minutes apart at different places: the K2 overlap case.
const crowded = [
  remark(450, 465, 'Springfield, MO', 'Post-trip inspection'),
  remark(465, 1065, 'Joplin, MO', '10-hour rest', 'SB'),
  remark(480, 510, 'Carthage, MO', 'Fuel'),
  remark(495, 525, 'Webb City, MO', '30-minute break'),
]
// Long place names, crowded and near midnight, where labels must wrap or shrink.
const longNames = [
  remark(0, 30, 'Spotsylvania Courthouse, VA', 'Pre-trip inspection'),
  remark(20, 50, 'Fredericksburg Industrial Park, VA', 'Fuel'),
  remark(40, 100, 'Rancho Santa Margarita, CA', 'Pickup'),
  remark(660, 675, 'Spotsylvania Courthouse, VA', 'Post-trip inspection'),
  remark(675, 1275, 'I 95 near Spotsylvania Courthouse, VA', '10-hour rest', 'SB'),
  remark(1380, 1410, 'Lake Havasu City Municipal Airport, AZ', '30-minute break', 'OFF'),
  remark(1425, 1440, 'Truth or Consequences, NM', 'Post-trip inspection'),
]

describe.each([
  ['crowded', crowded],
  ['long names', longNames],
])('layoutRemarks (%s)', (_, remarks) => {
  const layout = layoutRemarks(remarks, { fontSize: 10.5, angle: 45 })

  it('lays out one label per remark group, in time order', () => {
    expect(layout).toHaveLength(groupRemarks(remarks).length)
    for (let i = 1; i < layout.length; i++) expect(layout[i].anchorX).toBeGreaterThan(layout[i - 1].anchorX)
  })

  it('never truncates: the lines hold the whole label', () => {
    for (const l of layout) {
      expect(l.lines.join(' — ')).toBe(l.text)
      expect(l.text).not.toContain('…')
      expect(l.text.startsWith(l.group.location)).toBe(true)
      expect(l.fontSize).toBeGreaterThanOrEqual(REMARK_MIN_FONT)
    }
  })

  it('never lets two rotated labels overlap', () => {
    for (let i = 0; i < layout.length; i++) {
      for (let j = i + 1; j < layout.length; j++) {
        expect(polygonsIntersect(labelCorners(layout[i]), labelCorners(layout[j]))).toBe(false)
      }
    }
  })

  it('routes leader lines around the other labels', () => {
    const displaced = layout.filter((l) => l.displaced)
    expect(displaced.length).toBeGreaterThan(0)
    for (const l of displaced) {
      const pts = leaderPoints(l)
      for (const other of layout) {
        if (other === l) continue
        const box = labelCorners(other as RemarkLayout)
        for (let k = 0; k < pts.length - 1; k++) expect(segmentHitsPolygon(pts[k], pts[k + 1], box)).toBe(false)
      }
    }
  })

  it('keeps labels inside the remarks area (the frame sits 6 px below REMARKS.bottom)', () => {
    for (const l of layout) {
      // The layout fits the baseline; descenders may hang a few px lower.
      const descender = l.fontSize * 0.25
      for (const [x, y] of labelCorners(l)) {
        expect(x).toBeLessThanOrEqual(REMARKS.rightLimit + descender)
        expect(y).toBeLessThanOrEqual(REMARKS.bottom + descender)
      }
    }
  })
})

describe('layoutRemarks wrapping', () => {
  it('wraps a long label as "City, ST" over the activity instead of cutting it', () => {
    const [l] = layoutRemarks([remark(1380, 1410, 'Lake Havasu City Municipal Airport, AZ', '30-minute break', 'OFF')])
    expect(l.lines).toEqual(['Lake Havasu City Municipal Airport, AZ', '30-min break'])
  })
  it('keeps short labels on one line at full size', () => {
    const [l] = layoutRemarks([remark(600, 630, 'Joplin, MO', 'Fuel')], { fontSize: 10.5 })
    expect(l.lines).toEqual(['Joplin, MO — Fuel'])
    expect(l.fontSize).toBe(10.5)
  })
})

describe('recapValues', () => {
  it('fills A and C with the conservative cycle total and B with 70 - A', () => {
    const segments: LogSegment[] = [
      { status: 'OFF', start_minute: 0, end_minute: 360 },
      { status: 'ON', start_minute: 360, end_minute: 390 },
      { status: 'D', start_minute: 390, end_minute: 1050 },
      { status: 'SB', start_minute: 1050, end_minute: 1440 },
    ]
    expect(recapValues({ segments, cycle_hours_used: 41.5 })).toEqual({ onDutyTodayMinutes: 690, a: 41.5, b: 28.5, c: 41.5 })
  })
  it('never shows negative hours available', () => {
    expect(recapValues({ segments: [], cycle_hours_used: 70.25 }).b).toBe(0)
  })
})

describe('duty graph and totals', () => {
  const segments: LogSegment[] = [
    { status: 'OFF', start_minute: 0, end_minute: 360 },
    { status: 'ON', start_minute: 360, end_minute: 395 },
    { status: 'D', start_minute: 395, end_minute: 725.5 },
    { status: 'ON', start_minute: 725.5, end_minute: 755 },
    { status: 'SB', start_minute: 755, end_minute: 1440 },
  ]

  it('draws one continuous path (a single move-to)', () => {
    const path = buildDutyPath(segments)
    expect(path.match(/M/g)).toHaveLength(1)
    expect(path.startsWith('M')).toBe(true)
  })

  it('rounds row totals to whole minutes that add up to 24:00', () => {
    const rounded = roundedMinutesByStatus(minutesByStatus(segments))
    expect(Object.values(rounded).reduce((a, b) => a + b, 0)).toBe(1440)
    for (const v of Object.values(rounded)) expect(Number.isInteger(v)).toBe(true)
  })
})

describe('restartState', () => {
  it('is "completed" when a restart ends exactly at midnight and the cycle has reset', () => {
    expect(restartState([remark(0, 1440, 'Tulsa, OK', '34-hour restart (cont.)')], 0)).toBe('completed')
  })
  it('is "in-progress" when a restart runs through midnight with hours still on the cycle', () => {
    expect(restartState([remark(600, 1440, 'Tulsa, OK', '34-hour restart')], 69.5)).toBe('in-progress')
  })
  it('is "completed" when a restart ends during the day', () => {
    expect(restartState([remark(0, 600, 'Tulsa, OK', '34-hour restart (cont.)')], 1)).toBe('completed')
  })
  it('is null without a restart', () => {
    expect(restartState([remark(0, 600, 'Tulsa, OK', '10-hour rest')], 20)).toBeNull()
  })
})
