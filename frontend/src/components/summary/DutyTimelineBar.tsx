import { useMemo, useState } from 'react'
import { DUTY_ORDER, DUTY_STATUS } from '../../lib/duty'
import { cn } from '../../lib/cn'
import { formatClock, formatDay, formatDuration, minutesBetween, parseWallTime, placeLabel } from '../../lib/format'
import type { DutyStatus, TimelineEvent } from '../../types/api'
import { dayLabels } from './summaryModel'

interface DutyTimelineBarProps {
  timeline: TimelineEvent[]
  /** Home-terminal zone abbreviation for the start/end clocks. */
  tzAbbr?: string
  className?: string
}

/** Whole-trip strip chart: one block per event, width proportional to time, colored by duty status. */
export function DutyTimelineBar({ timeline, tzAbbr, className }: DutyTimelineBarProps) {
  const [hover, setHover] = useState<TimelineEvent | null>(null)

  const model = useMemo(() => {
    if (!timeline.length) return null
    const start = timeline[0].start
    const end = timeline[timeline.length - 1].end
    const total = Math.max(1, minutesBetween(start, end))
    const pct = (at: string) => (minutesBetween(start, at) / total) * 100

    // Midnight markers inside the trip span.
    const midnights: Array<{ left: number; label: string }> = []
    const d = parseWallTime(start)
    d.setUTCHours(24, 0, 0, 0)
    for (let day = 2; d.getTime() < parseWallTime(end).getTime(); day++) {
      const iso = d.toISOString().slice(0, 16)
      midnights.push({ left: pct(iso), label: `Day ${day}` })
      d.setUTCDate(d.getUTCDate() + 1)
    }

    const labels = dayLabels(midnights)

    const totals: Record<DutyStatus, number> = { OFF: 0, SB: 0, D: 0, ON: 0 }
    for (const e of timeline) totals[e.status] += e.duration_hours
    return { total, pct, midnights, labels, totals, start, end }
  }, [timeline])

  if (!model) return null

  return (
    <div className={className}>
      <div className="relative pt-4">
        {model.labels.map((m) => (
          <span
            key={m.label}
            className={cn(
              'absolute top-0 font-mono text-[10px] font-medium whitespace-nowrap text-ink-400',
              // Each day's label starts at its midnight line; one near the right end is right-aligned.
              m.left > 92 ? '-translate-x-full -ml-0.5' : 'translate-x-0.5',
            )}
            style={{ left: `${m.left}%` }}
          >
            {m.label}
          </span>
        ))}
        <div
          role="img"
          aria-label={`Duty timeline: ${DUTY_ORDER.map((s) => `${DUTY_STATUS[s].label} ${formatDuration(model.totals[s])}`).join(', ')}`}
          className="relative flex h-7 overflow-hidden rounded-md bg-ink-150 ring-1 ring-ink-900/5"
          onMouseLeave={() => setHover(null)}
        >
          {timeline.map((e) => (
            <div
              key={e.id}
              onMouseEnter={() => setHover(e)}
              className={cn('h-full transition-opacity', hover && hover.id !== e.id && 'opacity-45')}
              style={{
                width: `${(e.duration_hours * 60 * 100) / model.total}%`,
                backgroundColor: DUTY_STATUS[e.status].color,
                boxShadow: 'inset -1px 0 0 rgb(255 255 255 / 0.35)',
              }}
            />
          ))}
          {model.midnights.map((m) => (
            <span
              key={m.label}
              aria-hidden
              className="pointer-events-none absolute inset-y-0 w-px bg-ink-900/60"
              style={{ left: `${m.left}%` }}
            />
          ))}
        </div>
        <div className="mt-1 flex justify-between font-mono text-[10px] text-ink-400 tabular">
          <span>
            {formatDay(model.start)} {formatClock(model.start)} {tzAbbr}
          </span>
          <span>
            {formatDay(model.end)} {formatClock(model.end)} {tzAbbr}
          </span>
        </div>
      </div>

      <div className="mt-2 min-h-10" aria-live="polite">
        {hover ? (
          <p className="text-xs leading-5 text-ink-700">
            <span className="font-semibold text-ink-900">{hover.label}</span>
            <span className="tabular font-mono text-ink-500">
              {' '}
              · {formatDay(hover.start)} {formatClock(hover.start)}–{formatClock(hover.end)} ·{' '}
              {formatDuration(hover.duration_hours)}
            </span>
            <br />
            <span className="text-ink-500">{placeLabel(hover.start_location.name)}</span>
          </p>
        ) : (
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-600">
            {DUTY_ORDER.map((s) => (
              <li key={s} className="inline-flex items-center gap-1.5">
                <span className={cn('size-2.5 rounded-[3px]', DUTY_STATUS[s].dot)} aria-hidden />
                {DUTY_STATUS[s].label}
                <span className="tabular font-mono font-medium text-ink-900">{formatDuration(model.totals[s])}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
