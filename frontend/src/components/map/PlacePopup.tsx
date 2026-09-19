import { MoonStar } from 'lucide-react'
import { DUTY_HEX, EVENT_KIND } from '../../lib/duty'
import { formatClock, formatDay, formatDuration, formatMiles, placeLabel } from '../../lib/format'
import { homeClock, localTimeNote, outsideDockHours } from '../../lib/localTime'
import type { MapPlace } from './mapModel'

const city = (name: string) => placeLabel(name, { withRoad: false })

const ROLE_TITLE = { current: 'Start', pickup: 'Pickup', dropoff: 'Dropoff' } as const

/** `homeTzAbbr` labels the (home-terminal) clock times; local times are added where they differ. */
export function PlacePopup({ place, homeTzAbbr }: { place: MapPlace; homeTzAbbr?: string }) {
  const mile = place.stops[0]?.mile_marker
  // Markers rank stops by importance; the popup reads better in time order.
  // An endpoint pin also lists the stops drawn under it at this zoom (MapPlace.nearby).
  const nearby = new Set((place.nearby ?? []).map((s) => s.id))
  const stops = [...place.stops, ...(place.nearby ?? [])].sort((a, b) => a.start.localeCompare(b.start))
  const here = city(place.stops[0]?.location.name ?? place.title)
  const title = place.stops[0] ? placeLabel(place.stops[0].location.name) : place.title
  return (
    <div className="w-[268px] text-ink-900">
      <div className="border-b border-ink-100 px-3.5 pt-3 pb-2.5">
        <p className="text-[10px] font-semibold tracking-[0.14em] text-ink-500 uppercase">
          {place.role ? ROLE_TITLE[place.role] : 'Stop'}
          {mile !== undefined && <span className="tabular"> · Mile {formatMiles(mile, { unit: false })}</span>}
        </p>
        <p className="mt-0.5 truncate font-display text-[15px] leading-snug font-bold">
          {title}
        </p>
      </div>
      {stops.length > 0 ? (
        <ul className="max-h-56 divide-y divide-ink-100 overflow-auto">
          {stops.map((s) => {
            const Icon = EVENT_KIND[s.kind].icon
            const sameDay = s.start.slice(0, 10) === s.end.slice(0, 10)
            const local = localTimeNote(s.start, s.local_start, s.local_tz_abbr)
            const dock = (s.kind === 'pickup' || s.kind === 'dropoff') && outsideDockHours(s.local_start ?? s.start)
            // A marker merged from nearby stops (see clusterPlaces) names each stop's own place.
            const where = placeLabel(s.location.name)
            const elsewhere = nearby.has(s.id) || city(s.location.name) !== here
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
                    {homeClock(s.end, homeTzAbbr)}
                  </p>
                  {elsewhere && (
                    <p className="truncate text-[11px] text-ink-600">
                      {nearby.has(s.id) && 'Nearby · '}
                      {where}
                    </p>
                  )}
                  {s.reason && <p className="text-[11px] leading-snug text-ink-500">{s.reason}</p>}
                  {local && (
                    <p className="tabular font-mono text-[11px] text-ink-500">
                      {homeClock(s.start, homeTzAbbr)} · <span className="font-semibold text-ink-700">{local}</span>
                    </p>
                  )}
                  {dock && (
                    <p className="mt-1 inline-flex items-center gap-1 rounded-md bg-duty-on-soft px-1.5 py-0.5 text-[11px] font-semibold text-[#92400e] ring-1 ring-duty-on/30 ring-inset">
                      <MoonStar className="size-3" aria-hidden /> Outside typical dock hours
                    </p>
                  )}
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
