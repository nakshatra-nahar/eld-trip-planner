import { ArrowRight } from 'lucide-react'
import { useMemo } from 'react'
import { DUTY_ORDER, DUTY_STATUS, EVENT_KIND } from '../../lib/duty'
import { cn } from '../../lib/cn'
import { formatClock, formatDay, formatDayLong, formatDuration, formatMiles, placeLabel } from '../../lib/format'
import type { DailyLog, TimelineEvent } from '../../types/api'
import { StatusChip } from '../ui'

interface ItineraryViewProps {
  timeline: TimelineEvent[]
  dailyLogs: DailyLog[]
  selectedId: string | null
  onSelect: (event: TimelineEvent) => void
}

/** Vertical timeline grouped by the calendar day each event starts on. */
export function ItineraryView({ timeline, dailyLogs, selectedId, onSelect }: ItineraryViewProps) {
  const days = useMemo(() => {
    const byDate = new Map<string, TimelineEvent[]>()
    for (const e of timeline) {
      const date = e.start.slice(0, 10)
      byDate.set(date, [...(byDate.get(date) ?? []), e])
    }
    return [...byDate.entries()].map(([date, events]) => ({
      date,
      events,
      log: dailyLogs.find((l) => l.date === date),
    }))
  }, [timeline, dailyLogs])

  return (
    <div className="grid gap-10">
      {days.map(({ date, events, log }) => (
        <section
          key={date}
          aria-labelledby={`day-${date}`}
          className="grid gap-4 lg:grid-cols-[272px_minmax(0,1fr)] lg:gap-10"
        >
          <DayHeader date={date} log={log} />
          <ol className="relative max-w-6xl">
            {events.map((e, i) => (
              <ItineraryRow
                key={e.id}
                event={e}
                last={i === events.length - 1}
                selected={e.id === selectedId}
                onSelect={() => onSelect(e)}
              />
            ))}
          </ol>
        </section>
      ))}
    </div>
  )
}

/** Day card: date, a mini 24-hour duty strip (like the log grid) and the day's totals. */
function DayHeader({ date, log }: { date: string; log?: DailyLog }) {
  return (
    <header className="self-start rounded-xl bg-ink-50 p-4 ring-1 ring-ink-150 ring-inset lg:sticky lg:top-[80px]">
      <h3 id={`day-${date}`} className="flex items-baseline gap-2">
        <span className="font-display text-lg font-extrabold tracking-tight text-hw-700">
          Day {log?.day_number ?? '–'}
        </span>
        <span className="text-sm font-semibold text-ink-900">{formatDayLong(date).replace(/, \d{4}$/, '')}</span>
      </h3>
      {log && (
        <>
          <div className="mt-3">
            <div className="flex h-3 overflow-hidden rounded-[4px] ring-1 ring-ink-900/5" aria-hidden>
              {log.segments.map((seg) => (
                <span
                  key={seg.start_minute}
                  style={{
                    width: `${((seg.end_minute - seg.start_minute) / 1440) * 100}%`,
                    backgroundColor: DUTY_STATUS[seg.status].color,
                  }}
                />
              ))}
            </div>
            <div className="mt-1 flex justify-between font-mono text-[10px] text-ink-400">
              <span>00</span>
              <span>06</span>
              <span>12</span>
              <span>18</span>
              <span>24</span>
            </div>
          </div>
          <dl className="mt-3 grid grid-cols-4 gap-1 text-center lg:grid-cols-2 lg:text-left">
            {DUTY_ORDER.map((st) => (
              <div key={st} className="rounded-md bg-white px-2 py-1.5 ring-1 ring-ink-150 ring-inset">
                <dt className="flex items-center justify-center gap-1 text-[10px] font-medium text-ink-500 lg:justify-start">
                  <span className={cn('size-2 rounded-[2px]', DUTY_STATUS[st].dot)} aria-hidden />
                  {DUTY_STATUS[st].short}
                  <span className="sr-only">{DUTY_STATUS[st].label}</span>
                </dt>
                <dd className="tabular font-mono text-[13px] font-semibold text-ink-900">
                  {formatDuration(log.totals[st])}
                </dd>
              </div>
            ))}
          </dl>
          <p className="tabular mt-3 flex justify-between font-mono text-xs text-ink-600">
            <span>
              <span className="font-semibold text-ink-900">{formatMiles(log.total_miles)}</span> driven
            </span>
            <span>
              cycle <span className="font-semibold text-ink-900">{formatDuration(log.cycle_hours_used)}</span> of 70h
            </span>
          </p>
        </>
      )}
    </header>
  )
}

function ItineraryRow({
  event: e,
  last,
  selected,
  onSelect,
}: {
  event: TimelineEvent
  last: boolean
  selected: boolean
  onSelect: () => void
}) {
  const kind = EVENT_KIND[e.kind]
  const status = DUTY_STATUS[e.status]
  const Icon = kind.icon
  const drive = e.kind === 'drive'
  const crossesMidnight = e.start.slice(0, 10) !== e.end.slice(0, 10)

  return (
    <li className="relative grid grid-cols-[4.25rem_1.75rem_minmax(0,1fr)] gap-x-2 sm:grid-cols-[6.5rem_2rem_minmax(0,1fr)] sm:gap-x-3">
      <div className="pt-3 text-right">
        <p className="tabular font-mono text-[13px] font-semibold text-ink-900">{formatClock(e.start)}</p>
        <p className="tabular font-mono text-[11px] text-ink-400">
          {crossesMidnight && <span className="hidden sm:inline">{formatDay(e.end).split(',')[0]} </span>}
          {formatClock(e.end)}
        </p>
      </div>

      {/* Rail: status-colored line for driving, dot + icon for stops. */}
      <div className="relative flex justify-center">
        <span
          aria-hidden
          className={cn('absolute top-0 w-[3px]', last ? 'h-6' : 'bottom-0', drive ? 'rounded-full' : 'bg-ink-200')}
          style={drive ? { backgroundColor: status.color } : undefined}
        />
        <span
          aria-hidden
          className={cn(
            'relative mt-3 grid place-items-center rounded-full ring-4 ring-white',
            drive ? 'size-6 bg-white text-duty-d ring-offset-0' : 'size-7 text-white',
          )}
          style={drive ? { boxShadow: `inset 0 0 0 2px ${status.color}` } : { backgroundColor: status.color }}
        >
          <Icon className={drive ? 'size-3' : 'size-3.5'} strokeWidth={2.4} />
        </span>
      </div>

      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={cn(
          // On wide screens the row reads as a table line (what · where · miles) instead of a
          // narrow stack, so the timeline uses the width next to the day card.
          'group mb-1.5 min-h-14 w-full rounded-xl px-3 py-2.5 text-left transition-colors xl:grid xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1.35fr)_minmax(0,0.8fr)] xl:items-center xl:gap-5',
          selected ? 'bg-hw-50 ring-1 ring-hw-200' : 'hover:bg-ink-50',
        )}
      >
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-semibold text-ink-900">{e.label}</span>
          <StatusChip status={e.status} />
          <span className="tabular font-mono text-xs text-ink-500">{formatDuration(e.duration_hours)}</span>
        </div>
        <p className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1.5 text-[13px] text-ink-600 xl:mt-0">
          {drive ? (
            <>
              <span className="truncate">{placeLabel(e.start_location.name)}</span>
              <ArrowRight className="size-3 shrink-0 text-ink-400" aria-label="to" />
              <span className="truncate">{placeLabel(e.end_location.name)}</span>
            </>
          ) : (
            <span className="truncate">{placeLabel(e.start_location.name)}</span>
          )}
        </p>
        <p className="tabular mt-0.5 font-mono text-[11px] text-ink-400 xl:mt-0 xl:text-right">
          {drive ? (
            <>
              <span className="font-semibold text-duty-d-ink">{formatMiles(e.miles)}</span> · mile{' '}
              {formatMiles(e.start_mile, { unit: false })}–{formatMiles(e.end_mile, { unit: false })}
            </>
          ) : (
            <>mile {formatMiles(e.start_mile, { unit: false })}</>
          )}
          {e.leg_index === 0 ? ' · to pickup' : ''}
        </p>
      </button>
    </li>
  )
}
