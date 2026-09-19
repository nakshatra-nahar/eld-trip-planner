import { BedDouble, CalendarDays, ChevronDown, Coffee, Fuel, Gauge, Hourglass, Info, RotateCcw, Timer, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'
import { formatDuration, formatMiles, placeLabel } from '../../lib/format'
import type { PlanResponse } from '../../types/api'
import { Card, Skeleton } from '../ui'
import { DutyTimelineBar } from './DutyTimelineBar'

export function TripSummary({ plan }: { plan: PlanResponse }) {
  const { summary, route, input, warnings, assumptions } = plan
  const legs = route.legs
  const cycleTone =
    summary.cycle_hours_available_at_end <= 0 ? 'danger' : summary.cycle_hours_available_at_end < 11 ? 'warn' : 'ok'

  return (
    <Card className="animate-fade-up overflow-hidden">
      {/* Hero: total miles on an ink "sign" panel, with the three-stop route underneath. */}
      <div className="relative overflow-hidden bg-ink-900 px-5 pt-4 pb-5 text-white sm:px-6">
        <div
          aria-hidden
          className="absolute inset-x-0 bottom-0 h-1 bg-[repeating-linear-gradient(90deg,var(--color-hw-500)_0_22px,transparent_22px_34px)]"
        />
        <p className="text-[11px] font-semibold tracking-[0.14em] text-ink-300 uppercase">Trip summary</p>
        <div className="mt-1 flex items-end justify-between gap-4">
          <p className="font-display leading-none font-extrabold tracking-tight">
            <span className="tabular text-[40px]">{formatMiles(summary.total_miles, { unit: false })}</span>
            <span className="ml-1.5 text-lg font-bold text-ink-300">mi</span>
          </p>
          <p className="pb-1 text-right text-xs text-ink-300">
            <span className="tabular block font-mono text-sm font-semibold text-white">
              {formatDuration(summary.trip_duration_hours, { days: true })}
            </span>
            door to door
          </p>
        </div>
        <ol className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] text-ink-200">
          <li className="font-medium text-white">{placeLabel(input.current_location.label)}</li>
          {legs[0]?.distance_miles > 0.1 && (
            <li className="tabular font-mono text-[11px] text-ink-300">— {formatMiles(legs[0].distance_miles)} →</li>
          )}
          <li className="font-medium text-hw-300">{placeLabel(input.pickup_location.label)}</li>
          <li className="tabular font-mono text-[11px] text-ink-300">— {formatMiles(legs[1]?.distance_miles ?? 0)} →</li>
          <li className="font-medium text-white">{placeLabel(input.dropoff_location.label)}</li>
        </ol>
      </div>

      <dl className="grid grid-cols-2 gap-px bg-ink-150 min-[400px]:grid-cols-4">
        <Stat icon={<Gauge />} label="Driving" value={formatDuration(summary.total_driving_hours)} />
        <Stat
          icon={<Timer />}
          label="On-duty total"
          value={formatDuration(summary.total_on_duty_hours)}
          sub={`incl. ${formatDuration(summary.total_driving_hours)} driving`}
        />
        <Stat icon={<CalendarDays />} label="Log sheets" value={String(summary.num_days)} />
        <Stat icon={<Fuel />} label="Fuel stops" value={String(summary.num_fuel_stops)} />
        <Stat icon={<BedDouble />} label="10-hr rests" value={String(summary.num_rests)} />
        <Stat icon={<RotateCcw />} label="34-hr restarts" value={String(summary.num_restarts)} />
        <Stat
          icon={<Coffee />}
          label="30-min breaks"
          value={String(summary.num_breaks)}
          sub={summary.num_breaks === 0 ? 'Not needed separately' : undefined}
        />
        <Stat
          icon={<Hourglass />}
          label="Cycle left at end"
          value={formatDuration(summary.cycle_hours_available_at_end)}
          sub={`${formatDuration(summary.cycle_hours_used_at_end)} of 70h used`}
          tone={cycleTone}
        />
      </dl>

      <div className="px-5 pt-4 pb-3 sm:px-6">
        <h2 className="text-[11px] font-semibold tracking-[0.14em] text-ink-500 uppercase">Duty status over the trip</h2>
        <DutyTimelineBar timeline={plan.timeline} className="mt-1" />
      </div>

      {warnings.length > 0 && (
        <div className="px-5 pb-4 sm:px-6">
          <ul className="grid gap-2">
            {warnings.map((w) => (
              <li
                key={w}
                className="flex gap-2.5 rounded-lg bg-duty-on-soft px-3 py-2.5 text-[13px] leading-snug text-[#7c2d12] ring-1 ring-duty-on/25 ring-inset"
              >
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-duty-on" aria-hidden />
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="group border-t border-ink-150 px-5 sm:px-6">
        <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 text-sm font-semibold text-ink-700 [&::-webkit-details-marker]:hidden">
          <Info className="size-4 text-ink-400" aria-hidden />
          Assumptions ({assumptions.length})
          <ChevronDown className="ml-auto size-4 text-ink-400 transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <ul className="grid list-disc gap-1.5 pb-4 pl-5 text-[13px] leading-snug text-ink-600 marker:text-ink-300">
          {assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
          <li className="list-none text-xs text-ink-400">Routing: {route.provider}</li>
        </ul>
      </details>
    </Card>
  )
}

function Stat({
  icon,
  label,
  value,
  sub,
  tone = 'ok',
}: {
  icon: ReactNode
  label: string
  value: string
  sub?: string
  tone?: 'ok' | 'warn' | 'danger'
}) {
  return (
    <div className="bg-white px-3.5 py-3">
      <dt className="flex items-start gap-1.5 leading-tight text-[11px] font-medium text-ink-500 [&_svg]:mt-px [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-ink-400">
        {icon}
        {label}
      </dt>
      {/* A <dl> group may hold only <dt>/<dd>, so the subline lives inside the <dd>. */}
      <dd className="mt-1">
        <span
          className={cn(
            'tabular block font-display text-[19px] leading-none font-bold tracking-tight whitespace-nowrap',
            tone === 'ok' && 'text-ink-900',
            tone === 'warn' && 'text-[#b45309]',
            tone === 'danger' && 'text-danger-700',
          )}
        >
          {value}
        </span>
        {sub && <span className="mt-1 block text-[11px] leading-tight text-ink-500">{sub}</span>}
      </dd>
    </div>
  )
}

export function TripSummarySkeleton() {
  return (
    <Card className="overflow-hidden" aria-busy aria-label="Loading trip summary">
      <div className="bg-ink-900 px-6 pt-4 pb-5">
        <Skeleton className="h-3 w-24 opacity-20" />
        <Skeleton className="mt-3 h-10 w-44 opacity-20" />
        <Skeleton className="mt-4 h-3.5 w-64 opacity-20" />
      </div>
      <div className="grid grid-cols-2 gap-px bg-ink-150 min-[400px]:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="bg-white px-4 py-3.5">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-2 h-5 w-14" />
          </div>
        ))}
      </div>
      <div className="px-6 py-5">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="mt-4 h-7 w-full" />
      </div>
    </Card>
  )
}
