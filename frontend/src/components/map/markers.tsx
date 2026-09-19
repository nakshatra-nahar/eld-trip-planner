import type { PointerEvent } from 'react'
import { DUTY_HEX, EVENT_KIND, ROLE_ICON } from '../../lib/duty'
import { cn } from '../../lib/cn'
import type { EndpointRole, MapPlace } from './mapModel'

/**
 * Hover previews only for a real mouse: on touch, pointerenter fires on every tap and never
 * leaves, which kept an old popup open when the next marker was tapped.
 */
const mouseOnly = (fn?: (hovering: boolean) => void, value = true) => (e: PointerEvent) => {
  if (e.pointerType === 'mouse') fn?.(value)
}

const ROLE_STYLE: Record<EndpointRole, { fill: string; label: string }> = {
  current: { fill: '#0f1729', label: 'Start' },
  pickup: { fill: '#ef6c11', label: 'Pickup' },
  dropoff: { fill: '#0f1729', label: 'Dropoff' },
}

interface EndpointPinProps {
  role: EndpointRole
  label: string
  active?: boolean
  onHover?: (hovering: boolean) => void
}

/** Teardrop pin for the current, pickup and dropoff locations. Clicks are handled by the parent Marker. */
export function EndpointPin({ role, label, active = false, onHover }: EndpointPinProps) {
  const Icon = ROLE_ICON[role]
  const style = ROLE_STYLE[role]
  const interactive = Boolean(onHover)
  const Tag = interactive ? 'button' : 'div'
  return (
    <Tag
      {...(interactive ? { type: 'button' as const } : {})}
      aria-label={`${style.label}: ${label}`}
      onPointerEnter={mouseOnly(onHover)}
      onPointerLeave={mouseOnly(onHover, false)}
      onFocus={() => onHover?.(true)}
      onBlur={() => onHover?.(false)}
      className={cn(
        'group relative block origin-bottom transition-transform duration-150',
        interactive && 'cursor-pointer hover:scale-110',
        active && 'scale-110',
      )}
    >
      <svg width="34" height="44" viewBox="0 0 34 44" aria-hidden className="drop-shadow-[0_3px_4px_rgb(8_14_28/0.35)]">
        <path
          d="M17 43c0 0 15-15.2 15-26A15 15 0 0 0 2 17c0 10.8 15 26 15 26z"
          fill={style.fill}
          stroke="white"
          strokeWidth="2"
        />
      </svg>
      <span className="absolute top-[7px] left-1/2 grid size-5 -translate-x-1/2 place-items-center text-white">
        <Icon className="size-[15px]" strokeWidth={2.5} aria-hidden />
      </span>
      {role === 'current' && (
        <span className="absolute top-[3px] left-1/2 size-[26px] -translate-x-1/2 rounded-full ring-2 ring-hw-400/80" aria-hidden />
      )}
    </Tag>
  )
}

interface StopMarkerProps {
  place: MapPlace
  active: boolean
  onHover: (hovering: boolean) => void
}

/** Round stop marker colored by duty status, with the most important activity's icon and a count badge. */
export function StopMarker({ place, active, onHover }: StopMarkerProps) {
  const primary = place.stops[0]
  const Icon = EVENT_KIND[primary.kind].icon
  const color = DUTY_HEX[primary.status]
  const big = primary.kind === 'rest' || primary.kind === 'restart'
  return (
    <button
      type="button"
      aria-label={`${place.stops.map((s) => s.label).join(', ')} at ${place.title}`}
      onPointerEnter={mouseOnly(onHover)}
      onPointerLeave={mouseOnly(onHover, false)}
      onFocus={() => onHover(true)}
      onBlur={() => onHover(false)}
      className={cn(
        'relative grid cursor-pointer place-items-center rounded-full text-white ring-[2.5px] ring-white transition-transform duration-150 hover:scale-115',
        'shadow-[0_2px_6px_rgb(8_14_28/0.35)]',
        big ? 'size-8' : 'size-7',
        active && 'scale-115 ring-hw-400',
      )}
      style={{ backgroundColor: color }}
    >
      <Icon className={big ? 'size-4' : 'size-3.5'} strokeWidth={2.4} aria-hidden />
      {place.stops.length > 1 && (
        <span className="tabular absolute -top-1.5 -right-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-ink-900 px-1 text-[10px] leading-none font-bold ring-2 ring-white">
          {place.stops.length}
        </span>
      )}
    </button>
  )
}
