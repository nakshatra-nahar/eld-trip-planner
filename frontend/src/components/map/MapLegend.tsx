import { ChevronDown } from 'lucide-react'
import { type Ref, useMemo } from 'react'
import { DUTY_HEX, EVENT_KIND } from '../../lib/duty'
import { cn } from '../../lib/cn'
import type { EventKind, PlanResponse } from '../../types/api'

const ORDER: EventKind[] = ['fuel', 'break', 'rest', 'restart', 'pre_trip', 'post_trip']

/** Map key: the two route legs and every stop kind present in this plan. */
export function MapLegend({
  plan,
  open,
  onToggle,
  ref,
}: {
  plan: PlanResponse
  open: boolean
  onToggle: () => void
  /** React 19 ref-as-prop: TripMap measures the expanded legend to pad the route fit. */
  ref?: Ref<HTMLDivElement>
}) {
  const kinds = useMemo(() => {
    const present = new Map<EventKind, (typeof plan.stops)[number]['status']>()
    for (const s of plan.stops) if (!present.has(s.kind)) present.set(s.kind, s.status)
    return ORDER.filter((k) => present.has(k)).map((k) => ({ kind: k, status: present.get(k)! }))
  }, [plan])
  const hasLeg0 = plan.route.legs[0]?.distance_miles > 0.1

  return (
    <div ref={ref} className="absolute top-2.5 left-28 z-[5] max-w-[calc(100%-10rem)] sm:top-auto sm:bottom-2.5 sm:left-2.5 sm:max-w-[calc(100%-7rem)] rounded-xl bg-white/95 text-ink-800 shadow-card ring-1 ring-ink-900/10 backdrop-blur">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex h-9 w-full items-center gap-2 px-3 text-[11px] font-semibold tracking-[0.12em] text-ink-500 uppercase"
      >
        Legend
        <ChevronDown className={cn('ml-auto size-3.5 transition-transform', !open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <ul className="grid gap-1.5 px-3 pb-3 text-xs">
          {hasLeg0 && (
            <li className="flex items-center gap-2">
              <svg width="26" height="6" aria-hidden>
                <line x1="1" y1="3" x2="25" y2="3" stroke="#2a3754" strokeWidth="3" strokeDasharray="5 3.5" />
              </svg>
              To pickup
            </li>
          )}
          <li className="flex items-center gap-2">
            <svg width="26" height="6" aria-hidden>
              <line x1="1" y1="3" x2="25" y2="3" stroke="#ef6c11" strokeWidth="4" strokeLinecap="round" />
            </svg>
            Loaded to dropoff
          </li>
          {kinds.map(({ kind, status }) => {
            const Icon = EVENT_KIND[kind].icon
            return (
              <li key={kind} className="flex items-center gap-2">
                <span
                  className="ml-1 grid size-[18px] place-items-center rounded-full text-white"
                  style={{ backgroundColor: DUTY_HEX[status] }}
                >
                  <Icon className="size-2.5" strokeWidth={2.6} aria-hidden />
                </span>
                <span className="ml-1">{EVENT_KIND[kind].label}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
