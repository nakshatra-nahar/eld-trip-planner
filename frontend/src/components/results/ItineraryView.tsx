import { ArrowRight, Clock, Globe2, MoonStar, Scale } from 'lucide-react'
import { useMemo } from 'react'
import { DUTY_ORDER, DUTY_STATUS, EVENT_KIND, stopReason } from '../../lib/duty'
import { cn } from '../../lib/cn'
import { formatClock, formatDay, formatDayLong, formatDuration, formatMiles, placeLabel } from '../../lib/format'
import { localTimeNote, outsideDockHours } from '../../lib/localTime'
import type { DailyLog, TimelineEvent } from '../../types/api'
import { Badge, StatusChip } from '../ui'
import { buildItineraryDays, carriedLabel, type ItineraryDay } from './itinerary'

interface ItineraryViewProps {
  timeline: TimelineEvent[]
  dailyLogs: DailyLog[]
  selectedId: string | null
  onSelect: (event: TimelineEvent) => void
  /** Home-terminal zone abbreviation, e.g. "CDT": the time base of every clock shown. */
  homeTzAbbr?: string
}

/** Vertical timeline with one group per log sheet (calendar day, home-terminal time). */
export function ItineraryView({ timeline, dailyLogs, selectedId, onSelect, homeTzAbbr }: ItineraryViewProps) {
  const days = useMemo(() => buildItineraryDays(timeline, dailyLogs), [timeline, dailyLogs])

  return (
    <div className="grid gap-6">
      <p className="flex items-center gap-1.5 text-xs text-ink-500">
        <Clock className="size-3.5 shrink-0 text-ink-400" aria-hidden />
        <span>
          Times are home-terminal time{homeTzAbbr ? <> (<span className="font-mono font-semibold text-ink-700">{homeTzAbbr}</span>)</> : null}, as on the logs. Local time is shown where a stop is in another zone.
        </span>
      </p>
      {days.map((day) => (
        <section
          key={day.date}
          aria-labelledby={`day-${day.date}`}
          className="grid gap-3 lg:grid-cols-[256px_minmax(0,1fr)] lg:gap-6"
        >
          <DayHeader day={day} />
          <ol className="relative max-w-6xl">
            {day.carried && <CarriedRow carried={day.carried} last={day.events.length === 0} />}
            {day.events.map((e, i) => (
              <ItineraryRow
                key={e.id}
                event={e}
                last={i === day.events.length - 1}
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
function DayHeader({ day: { date, log, note } }: { day: ItineraryDay }) {
  return (
    <header className="self-start rounded-xl bg-ink-50 p-4 ring-1 ring-ink-150 ring-inset lg:sticky lg:top-[80px]">
      <h3 id={`day-${date}`} className="flex items-baseline gap-2">
        <span className="font-display text-lg font-extrabold tracking-tight whitespace-nowrap text-hw-700">
          Day {log?.day_number ?? '–'}
        </span>
        <span className="text-sm font-semibold text-ink-900" title={formatDayLong(date)}>
          {formatDay(date)}
        </span>
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
      {note && (
        <p className="mt-3 flex gap-1.5 rounded-md bg-white px-2 py-1.5 text-[11px] leading-snug text-ink-700 ring-1 ring-ink-150 ring-inset">
          <Scale className="mt-px size-3.5 shrink-0 text-ink-400" aria-hidden />
          {note}
        </p>
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
  const reason = drive ? undefined : stopReason(e)
  const crossesMidnight = e.start.slice(0, 10) !== e.end.slice(0, 10)
  const local = drive ? null : localTimeNote(e.start, e.local_start, e.start_tz_abbr)
  const dock = (e.kind === 'pickup' || e.kind === 'dropoff') && outsideDockHours(e.local_start ?? e.start)

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
          {reason && <span className="basis-full text-xs leading-snug text-ink-500">{reason}</span>}
        </div>
        <p className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1.5 text-[13px] text-ink-600 xl:mt-0">
          {drive ? (
            <>
              <span className="truncate">{placeLabel(e.start_location.name)}</span>
              <ArrowRight className="size-3 shrink-0 text-ink-400" aria-label="to" />
              <span className="truncate">{placeLabel(e.end_location.name)}</span>
            </>
          ) : (
            <>
              <span className="truncate">{placeLabel(e.start_location.name)}</span>
              {local && (
                <span className="tabular inline-flex shrink-0 items-center gap-1 rounded bg-ink-100 px-1.5 font-mono text-[11px] text-ink-600">
                  <Globe2 className="size-3 text-ink-400" aria-hidden />
                  {local}
                </span>
              )}
            </>
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
        {dock && (
          <Badge tone="warning" className="mt-1 xl:col-span-3 xl:mt-0 xl:justify-self-start">
            <MoonStar className="size-3" aria-hidden />
            Outside typical dock hours ({formatClock(e.local_start ?? e.start)}
            {e.start_tz_abbr ? ` ${e.start_tz_abbr}` : ''} local)
          </Badge>
        )}
      </button>
    </li>
  )
}

/** A rest or restart that began on an earlier day and is still running at midnight. */
function CarriedRow({ carried, last }: { carried: NonNullable<ItineraryDay['carried']>; last: boolean }) {
  const { event: e, allDay } = carried
  const status = DUTY_STATUS[e.status]
  const Icon = EVENT_KIND[e.kind].icon
  return (
    <li className="relative grid grid-cols-[4.25rem_1.75rem_minmax(0,1fr)] gap-x-2 sm:grid-cols-[6.5rem_2rem_minmax(0,1fr)] sm:gap-x-3">
      <div className="pt-3 text-right">
        <p className="tabular font-mono text-[13px] font-semibold text-ink-400">00:00</p>
        <p className="tabular font-mono text-[11px] text-ink-400">{allDay ? '24:00' : formatClock(e.end)}</p>
      </div>
      <div className="relative flex justify-center">
        <span aria-hidden className={cn('absolute top-0 w-[3px] bg-ink-200', last ? 'h-6' : 'bottom-0')} />
        <span
          aria-hidden
          className="relative mt-3 grid size-7 place-items-center rounded-full bg-white ring-4 ring-white"
          style={{ boxShadow: `inset 0 0 0 2px ${status.color}`, color: status.color }}
        >
          <Icon className="size-3.5" strokeWidth={2.4} />
        </span>
      </div>
      <div
        className={cn(
          'mb-1.5 flex min-h-14 flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-dashed px-3 py-2.5',
          allDay ? 'border-ink-300 bg-ink-50' : 'border-ink-200',
        )}
      >
        <span className={cn('text-sm', allDay ? 'font-semibold text-ink-900' : 'text-ink-600')}>{carriedLabel(carried)}</span>
        <StatusChip status={e.status} />
        <span className="w-full text-[13px] text-ink-500">{placeLabel(e.start_location.name)}</span>
      </div>
    </li>
  )
}
