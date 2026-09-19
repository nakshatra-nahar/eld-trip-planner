import {
  ArrowUp,
  ArrowUpLeft,
  ArrowUpRight,
  ChevronDown,
  CornerUpLeft,
  CornerUpRight,
  Flag,
  GitFork,
  GitMerge,
  type LucideIcon,
  Navigation,
  RotateCw,
  Signpost,
  Undo2,
} from 'lucide-react'
import { useState } from 'react'
import { cn } from '../../lib/cn'
import { formatDuration, formatMiles } from '../../lib/format'
import type { Instruction, PlanResponse, RouteLeg } from '../../types/api'

function maneuverIcon({ maneuver, modifier }: Instruction): LucideIcon {
  if (maneuver === 'depart') return Navigation
  if (maneuver === 'arrive') return Flag
  if (maneuver === 'roundabout' || maneuver === 'rotary' || maneuver.startsWith('roundabout')) return RotateCw
  if (maneuver === 'merge') return GitMerge
  if (maneuver === 'fork') return GitFork
  if (maneuver === 'notification') return Signpost
  if (modifier === 'uturn') return Undo2
  if (modifier === 'left' || modifier === 'sharp left') return CornerUpLeft
  if (modifier === 'right' || modifier === 'sharp right') return CornerUpRight
  if (modifier === 'slight left') return ArrowUpLeft
  if (modifier === 'slight right') return ArrowUpRight
  return ArrowUp
}

export function DirectionsView({ plan }: { plan: PlanResponse }) {
  const { input } = plan
  const names = {
    current: input.current_location.label,
    pickup: input.pickup_location.label,
    dropoff: input.dropoff_location.label,
  }
  return (
    <div className="grid gap-4">
      {plan.route.legs.map((leg, i) => (
        <LegDirections
          key={i}
          index={i}
          leg={leg}
          from={names[leg.from_role]}
          to={names[leg.to_role]}
          defaultOpen={plan.route.legs.length === 1 || i === 0 || leg.distance_miles > 0.1}
        />
      ))}
      <p className="text-xs text-ink-400">
        Directions by {plan.route.provider}. Times are truck-adjusted (max 65 mph) and exclude HOS stops.
      </p>
    </div>
  )
}

function LegDirections({
  index,
  leg,
  from,
  to,
  defaultOpen,
}: {
  index: number
  leg: RouteLeg
  from: string
  to: string
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const empty = leg.distance_miles < 0.1 || leg.instructions.length === 0
  const id = `leg-${index}-steps`
  return (
    <section className="overflow-hidden rounded-xl ring-1 ring-ink-200">
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((o) => !o)}
          className="flex min-h-14 w-full items-center gap-3 bg-ink-50 px-4 py-3 text-left hover:bg-ink-100"
        >
          <span
            className={cn(
              'grid size-8 shrink-0 place-items-center rounded-lg font-display text-sm font-extrabold',
              index === 0 ? 'bg-ink-800 text-white' : 'bg-hw-500 text-white',
            )}
          >
            {index + 1}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-ink-900">
              {from} → {to}
            </span>
            <span className="tabular block font-mono text-xs text-ink-500">
              {formatMiles(leg.distance_miles)} · {formatDuration(leg.duration_hours)} driving ·{' '}
              {leg.instructions.length} steps
            </span>
          </span>
          <ChevronDown className={cn('size-4 shrink-0 text-ink-400 transition-transform', open && 'rotate-180')} aria-hidden />
        </button>
      </h3>
      <div id={id} hidden={!open}>
        {empty ? (
          <p className="px-4 py-4 text-sm text-ink-500">The truck is already at the pickup. No driving on this leg.</p>
        ) : (
          <ol className="divide-y divide-ink-100">
            {leg.instructions.map((step, i) => {
              const Icon = maneuverIcon(step)
              return (
                <li key={i} className="flex items-start gap-3 px-4 py-3">
                  <span
                    className={cn(
                      'mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg',
                      step.maneuver === 'arrive' ? 'bg-ink-900 text-white' : 'bg-ink-100 text-ink-700',
                    )}
                  >
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink-900">{step.text}</p>
                    {step.road && step.maneuver !== 'arrive' && (
                      <p className="mt-0.5 font-mono text-[11px] text-ink-400">{step.road}</p>
                    )}
                  </div>
                  {step.distance_miles > 0 && (
                    <span className="tabular shrink-0 pt-1 text-right font-mono text-xs text-ink-500">
                      {step.distance_miles < 0.05 ? '<0.1 mi' : formatMiles(step.distance_miles)}
                      <span className="block text-[11px] text-ink-400">
                        {step.duration_minutes < 0.5 ? '<1m' : formatDuration(step.duration_minutes / 60)}
                      </span>
                    </span>
                  )}
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </section>
  )
}
