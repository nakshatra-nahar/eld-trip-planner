import { DUTY_HEX, EVENT_KIND } from '../../lib/duty'
import { formatClock, formatDay, formatDuration, formatMiles } from '../../lib/format'
import type { MapPlace } from './mapModel'

const ROLE_TITLE = { current: 'Start', pickup: 'Pickup', dropoff: 'Dropoff' } as const

export function PlacePopup({ place }: { place: MapPlace }) {
  const mile = place.stops[0]?.mile_marker
  // Markers rank stops by importance; the popup reads better in time order.
  const stops = [...place.stops].sort((a, b) => a.start.localeCompare(b.start))
  return (
    <div className="w-[268px] text-ink-900">
      <div className="border-b border-ink-100 px-3.5 pt-3 pb-2.5">
        <p className="text-[10px] font-semibold tracking-[0.14em] text-ink-500 uppercase">
          {place.role ? ROLE_TITLE[place.role] : 'Stop'}
          {mile !== undefined && <span className="tabular"> · Mile {formatMiles(mile, { unit: false })}</span>}
        </p>
        <p className="mt-0.5 truncate font-display text-[15px] leading-snug font-bold">
          {place.stops[0]?.location.name ?? place.title}
        </p>
      </div>
      {place.stops.length > 0 ? (
        <ul className="max-h-56 divide-y divide-ink-100 overflow-auto">
          {stops.map((s) => {
            const Icon = EVENT_KIND[s.kind].icon
            const sameDay = s.start.slice(0, 10) === s.end.slice(0, 10)
            return (
              <li key={s.id} className="flex gap-2.5 px-3.5 py-2.5">
                <span
                  className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-white"
                  style={{ backgroundColor: DUTY_HEX[s.status] }}
                >
                  <Icon className="size-3.5" strokeWidth={2.4} aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="truncate text-[13px] font-semibold">{s.label}</p>
                    <p className="tabular shrink-0 font-mono text-[11px] font-medium text-ink-500">
                      {formatDuration(s.duration_hours)}
                    </p>
                  </div>
                  <p className="tabular font-mono text-[11px] text-ink-500">
                    {formatDay(s.start)} {formatClock(s.start)} → {sameDay ? '' : `${formatDay(s.end)} `}
                    {formatClock(s.end)}
                  </p>
                </div>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="px-3.5 py-2.5 text-xs text-ink-500">{place.title}</p>
      )}
    </div>
  )
}
