import { describe, expect, it } from 'vitest'
import type { LogRemark, LogSegment } from '../../types/api'
import {
  buildDutyPath,
  groupRemarks,
  labelCorners,
  layoutRemarks,
  leaderPoints,
  minutesByStatus,
  REMARKS,
  restartState,
  roundedMinutesByStatus,
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

const remark = (start: number, end: number, location: string, note: string): LogRemark => ({
  start_minute: start,
  end_minute: end,
  status: 'ON',
  location,
  note,
})

describe('groupRemarks', () => {
  it('merges consecutive remarks at the same place and keeps one form of the name', () => {
    const groups = groupRemarks([
      remark(450, 465, 'Joplin, MO', 'Post-trip inspection'),
      remark(465, 1065, 'I 44 near Joplin, MO', '10-hour rest'),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0].location).toBe('Joplin, MO')
    expect(groups[0].note).toBe('Post-trip, 10-hr rest')
    expect(groups[0].members).toHaveLength(2)
  })

  it('keeps remarks at different places apart', () => {
    expect(groupRemarks([remark(0, 60, 'Chicago, IL', 'Pre-trip'), remark(75, 105, 'Joliet, IL', 'Fuel')])).toHaveLength(2)
  })
})

describe('layoutRemarks', () => {
  // Remarks 15 minutes apart at different places: the K2 overlap case.
  const crowded = [
    remark(450, 465, 'Springfield, MO', 'Post-trip inspection'),
    remark(465, 1065, 'Joplin, MO', '10-hour rest'),
    remark(480, 510, 'Carthage, MO', 'Fuel'),
    remark(495, 525, 'Webb City, MO', '30-minute break'),
  ]
  const layout = layoutRemarks(crowded, { fontSize: 10.5, angle: 45 })

  it('lays out one label per remark group, in time order', () => {
    expect(layout).toHaveLength(4)
    for (let i = 1; i < layout.length; i++) expect(layout[i].anchorX).toBeGreaterThan(layout[i - 1].anchorX)
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
