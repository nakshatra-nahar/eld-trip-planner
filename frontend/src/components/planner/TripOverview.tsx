import { CalendarClock, Hourglass, PencilLine, Plus } from 'lucide-react'
import { cn } from '../../lib/cn'
import { ROLE_ICON } from '../../lib/duty'
import { formatDateTime, formatHours } from '../../lib/format'
import type { PlanResponse } from '../../types/api'
import { Button } from '../ui'

interface TripOverviewProps {
  plan: PlanResponse
  onEdit: () => void
  onNew: () => void
}

/** Compact read-only view of the planned trip's inputs, shown in place of the form after planning. */
export function TripOverview({ plan, onEdit, onNew }: TripOverviewProps) {
  const { input } = plan
  const stops = [
    { role: 'current' as const, title: 'Current', label: input.current_location.label },
    { role: 'pickup' as const, title: 'Pickup', label: input.pickup_location.label },
    { role: 'dropoff' as const, title: 'Dropoff', label: input.dropoff_location.label },
  ]
  return (
    <div className="p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-semibold tracking-[0.14em] text-hw-600 uppercase">Planned trip</p>
        <div className="flex shrink-0 gap-1">
          <Button size="sm" variant="secondary" onClick={onEdit} icon={<PencilLine className="size-3.5" aria-hidden />}>
            Edit
          </Button>
          <Button size="sm" variant="ghost" onClick={onNew} icon={<Plus className="size-3.5" aria-hidden />}>
            New trip
          </Button>
        </div>
      </div>
      <h1 className="mt-1 font-display text-[22px] leading-tight font-extrabold tracking-tight text-balance text-ink-900">
        {input.pickup_location.label} <span className="text-hw-500">→</span> {input.dropoff_location.label}
      </h1>

      <ol className="mt-4 grid gap-2.5">
        {stops.map((s, i) => {
          const Icon = ROLE_ICON[s.role]
          return (
            <li key={s.role} className="relative flex items-center gap-3">
              {i < stops.length - 1 && (
                <span
                  aria-hidden
                  className="absolute top-7 left-[13px] h-[14px] w-[2px] bg-[repeating-linear-gradient(to_bottom,var(--color-hw-400)_0_4px,transparent_4px_7px)]"
                />
              )}
              <span
                className={cn(
                  'grid size-7 shrink-0 place-items-center rounded-full',
                  s.role === 'current' && 'bg-white text-ink-900 ring-2 ring-ink-900',
                  s.role === 'pickup' && 'bg-hw-500 text-white',
                  s.role === 'dropoff' && 'bg-ink-900 text-white',
                )}
              >
                <Icon className="size-3.5" strokeWidth={2.4} aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block text-[11px] font-medium text-ink-500">{s.title}</span>
                <span className="block truncate text-sm font-semibold text-ink-900">{s.label}</span>
              </span>
            </li>
          )
        })}
      </ol>

      <dl className="mt-4 grid grid-cols-2 gap-2 text-[13px]">
        <div className="rounded-lg bg-ink-50 px-3 py-2 ring-1 ring-ink-150 ring-inset">
          <dt className="flex items-center gap-1.5 text-[11px] text-ink-500">
            <CalendarClock className="size-3.5" aria-hidden /> Start
          </dt>
          <dd className="tabular font-mono font-semibold text-ink-900">{formatDateTime(input.start_time)}</dd>
        </div>
        <div className="rounded-lg bg-ink-50 px-3 py-2 ring-1 ring-ink-150 ring-inset">
          <dt className="flex items-center gap-1.5 text-[11px] text-ink-500">
            <Hourglass className="size-3.5" aria-hidden /> Cycle used at start
          </dt>
          <dd className="tabular font-mono font-semibold text-ink-900">
            {formatHours(input.current_cycle_used_hours)} / 70 h
          </dd>
        </div>
      </dl>
    </div>
  )
}
