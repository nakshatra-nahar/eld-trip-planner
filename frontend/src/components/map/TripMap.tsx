import 'maplibre-gl/dist/maplibre-gl.css'
import { LoaderCircle, MapPinOff, Maximize2, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import MapGL, {
  AttributionControl,
  Layer,
  type LayerProps,
  type MapRef,
  Marker,
  NavigationControl,
  Popup,
  ScaleControl,
  Source,
} from 'react-map-gl/maplibre'
import type { Map as MapInstance, Offset as PopupOffset, StyleSpecification } from 'maplibre-gl'
import type { LngLat, PlanResponse } from '../../types/api'
import { formatDuration, formatMiles, placeLabel } from '../../lib/format'
import { prefersReducedMotion } from '../../lib/motion'
import { loadMaplibre } from './maplibre'
import { loadMapStyle } from './mapStyle'
import { MAP_LOAD_TIMEOUT_MS, type MapFailure, mapFailureOf, pageSupportsWebGL2, tilesDrawn } from './mapSupport'
import { MapLegend } from './MapLegend'
import { EndpointPin, StopMarker } from './markers'
import {
  type Bounds,
  boundsOf,
  buildPlaces,
  clusterPlaces,
  DEFAULT_VIEW,
  type MapFocus,
  type MapPlace,
  routeFeatures,
} from './mapModel'
import { PlacePopup } from './PlacePopup'

const ROUTE_CASING: LayerProps = {
  id: 'route-casing',
  type: 'line',
  layout: { 'line-join': 'round', 'line-cap': 'round' },
  paint: {
    'line-color': '#ffffff',
    'line-width': ['interpolate', ['linear'], ['zoom'], 3, 5, 10, 11],
    'line-opacity': 0.95,
  },
}
// Leg 0 (to pickup, typically empty) is a dashed ink line; leg 1 (loaded) is the solid highway-orange line.
const ROUTE_LEG0: LayerProps = {
  id: 'route-leg0',
  type: 'line',
  filter: ['==', ['get', 'leg'], 0],
  layout: { 'line-join': 'round', 'line-cap': 'butt' },
  paint: {
    'line-color': '#2a3754',
    'line-width': ['interpolate', ['linear'], ['zoom'], 3, 2.5, 10, 5],
    'line-dasharray': [2, 1.4],
  },
}
const ROUTE_LEG1: LayerProps = {
  id: 'route-leg1',
  type: 'line',
  filter: ['==', ['get', 'leg'], 1],
  layout: { 'line-join': 'round', 'line-cap': 'round' },
  paint: {
    'line-color': '#ef6c11',
    'line-width': ['interpolate', ['linear'], ['zoom'], 3, 3, 10, 6.5],
  },
}

// Endpoint pins are 34x44 and anchored at their tip, so the popup clears the pin's head.
const PIN_POPUP_OFFSET: PopupOffset = {
  top: [0, 0],
  'top-left': [0, 0],
  'top-right': [0, 0],
  bottom: [0, -46],
  'bottom-left': [0, -46],
  'bottom-right': [0, -46],
  left: [18, -22],
  right: [-18, -22],
  center: [0, -22],
}

// Start the MapLibre chunk and the basemap style together as soon as the app loads, instead
// of importing MapLibre only after the style has arrived (that serialised ~0.5 s of cold start).
const maplibrePromise = loadMaplibre()
void loadMapStyle()

/** Camera move length, or 0 when the viewer prefers reduced motion. */
const motion = (ms: number) => (prefersReducedMotion() ? 0 : ms)

export interface PreviewPoint {
  role: 'current' | 'pickup' | 'dropoff'
  lngLat: LngLat
  label: string
}

interface TripMapProps {
  plan: PlanResponse | null
  /** Pins for locations picked in the form before a plan exists. */
  preview: PreviewPoint[]
  focus: MapFocus | null
  selectedStopId: string | null
  onSelectStop: (stopId: string | null) => void
  loading: boolean
  /** The plan request has been running a while; the overlay explains the wait. */
  slow?: boolean
  /** One-click demo from the empty map. */
  onLoadSample?: () => void
}

function useIsNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 640px)').matches)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)')
    const onChange = () => setNarrow(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return narrow
}

// Stacking inside the map: stops < selected stop < endpoint pins < selected pin. Map
// controls (z 5) and the open popup (z 6, index.css) stay above all markers.
function markerZ(place: MapPlace, active: boolean): number {
  return (place.role ? 3 : 1) + (active ? 1 : 0)
}

export function TripMap({ plan, preview, focus, selectedStopId, onSelectStop, loading, slow = false, onLoadSample }: TripMapProps) {
  const mapRef = useRef<MapRef>(null)
  const legendRef = useRef<HTMLDivElement>(null)
  // `ready`: the map exists and its style is parsed, so the camera can frame the route (tiles may
  // still be downloading). `tilesLoaded`: the first view is fully drawn (`load`, `idle` or `sourcedata`).
  const [ready, setReady] = useState(false)
  const [tilesLoaded, setTilesLoaded] = useState(false)
  // No tiles drawn after MAP_LOAD_TIMEOUT_MS: "Loading map…" becomes a slow-connection note.
  const [tilesSlow, setTilesSlow] = useState(false)
  // Set when the map cannot be drawn at all (no WebGL 2, or MapLibre failed to start).
  const [failure, setFailure] = useState<MapFailure | null>(() => (pageSupportsWebGL2() ? null : 'webgl'))
  const [mapStyle, setMapStyle] = useState<StyleSpecification | string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [pinned, setPinned] = useState<string | null>(null)
  const narrow = useIsNarrow()
  // The legend covers too much of a small map: it starts folded, and opens on load when the map
  // itself (not the window) is at least 700 px wide.
  const [legendOpen, setLegendOpen] = useState(false)
  // The map and its zoom after the last camera move: marker clustering is recomputed from them.
  const [view, setView] = useState<{ map: MapInstance; zoom: number } | null>(null)

  useEffect(() => {
    if (tilesLoaded || failure) return
    const timer = window.setTimeout(() => setTilesSlow(true), MAP_LOAD_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [tilesLoaded, failure])

  useEffect(() => {
    let cancelled = false
    loadMapStyle().then((style) => !cancelled && setMapStyle(style))
    return () => {
      cancelled = true
    }
  }, [])

  const basePlaces = useMemo(() => (plan ? buildPlaces(plan) : []), [plan])
  const routeData = useMemo(() => (plan ? routeFeatures(plan) : null), [plan])
  const routeBounds = useMemo(() => (plan ? boundsOf(plan.route.geometry) : null), [plan])

  // Stop markers that would overlap at this zoom merge into one marker with a count badge.
  const places = useMemo(() => {
    if (!view) return basePlaces
    const { map } = view
    return clusterPlaces(basePlaces, (lngLat) => {
      const pt = map.project(lngLat)
      return [pt.x, pt.y]
    })
  }, [basePlaces, view])

  // Keep pins clear of the map buttons: pins rise ~40 px above their point, so the top padding
  // clears "Fit route" (and the legend button beside it on phones). On wider maps an expanded
  // legend (bottom-left) gets the left padding it actually needs, measured when fitting.
  const fit = useCallback(
    (bounds: Bounds | null, duration = 900) => {
      const map = mapRef.current
      if (!map || !bounds) return
      const legend = legendRef.current
      const legendWidth = !narrow && legend && legend.offsetHeight > 48 ? legend.offsetWidth + 20 : 0
      const padding = narrow
        ? { top: 96, bottom: 84, left: 52, right: 60 }
        : { top: 72, bottom: 56, left: Math.max(56, legendWidth), right: 72 }
      // A hidden or collapsed container cannot fit the padded bounds (MapLibre warns and bails).
      const el = map.getContainer()
      if (el.clientWidth <= padding.left + padding.right || el.clientHeight <= padding.top + padding.bottom) return
      map.fitBounds(bounds, { padding, duration: motion(duration), maxZoom: 11 })
    },
    [narrow],
  )

  // Frame the route whenever a new plan arrives.
  useEffect(() => {
    if (ready && routeBounds) fit(routeBounds)
  }, [ready, routeBounds, fit])

  // Before a plan exists, frame the locations picked in the form.
  const hasPlan = plan !== null
  useEffect(() => {
    if (!ready || hasPlan) return
    if (preview.length >= 2) fit(boundsOf(preview.map((p) => p.lngLat)))
    else if (preview.length === 1) mapRef.current?.flyTo({ center: preview[0].lngLat, zoom: 6, duration: motion(900) })
  }, [ready, hasPlan, preview, fit])

  // Fly to itinerary selections.
  useEffect(() => {
    if (!ready || !focus) return
    const map = mapRef.current
    if (!map) return
    if (focus.bounds) {
      fit(focus.bounds, 1000)
    } else if (focus.lngLat) {
      map.flyTo({ center: focus.lngLat, zoom: Math.max(map.getZoom(), 8), duration: motion(1100) })
    }
  }, [focus, ready, fit])

  const selectedPlaceKey = useMemo(
    () =>
      selectedStopId
        ? (places.find((p) => [...p.stops, ...(p.nearby ?? [])].some((s) => s.id === selectedStopId))?.key ?? null)
        : null,
    [places, selectedStopId],
  )
  const popupKey = hovered ?? pinned ?? selectedPlaceKey
  const popupPlace = places.find((p) => p.key === popupKey) ?? null

  const readyOnce = useRef(false)
  function onMapReady(map: MapInstance) {
    if (readyOnce.current) return
    readyOnce.current = true
    setReady(true)
    setView({ map, zoom: map.getZoom() })
    const el = map.getContainer()
    setLegendOpen(el.clientWidth >= 700)
    // On small maps the expanded attribution covers a band of the map: start it folded
    // to the (i) button, which still opens it.
    if (el.clientWidth < 640) el.querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show')
  }

  function selectPlace(place: MapPlace) {
    // One popup at a time: a tap replaces whatever is open (hover state included).
    setHovered(null)
    setPinned(place.key)
    // On phones the legend would cover the popup: fold it away while a place is open, and
    // centre the place so its popup fits beside it instead of running off the map's edge.
    if (narrow) {
      setLegendOpen(false)
      mapRef.current?.easeTo({ center: place.lngLat, offset: [0, -50], duration: motion(400) })
    }
    onSelectStop(place.stops[0]?.id ?? null)
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#eef0f3]">
      {/* Map controls come first in the DOM so they are first in tab order (they sit top-left),
          and stack above markers (z 1-4) but below an open popup (z 6). */}
      {plan && !failure && (
        <button
          type="button"
          onClick={() => fit(routeBounds)}
          className="absolute top-2.5 left-2.5 z-[5] inline-flex h-9 items-center gap-1.5 rounded-[10px] bg-white px-3 text-[13px] font-medium text-ink-800 shadow-card ring-1 ring-ink-900/10 hover:bg-ink-50"
        >
          <Maximize2 className="size-3.5" aria-hidden /> Fit route
        </button>
      )}
      {plan && !failure && <MapLegend ref={legendRef} plan={plan} open={legendOpen} onToggle={() => setLegendOpen((o) => !o)} />}

      {failure && <MapUnavailable failure={failure} plan={plan} />}

      {mapStyle && !failure && (
        <MapGL
          ref={mapRef}
          mapLib={maplibrePromise}
          initialViewState={DEFAULT_VIEW}
          mapStyle={mapStyle}
          attributionControl={false}
          dragRotate={false}
          touchPitch={false}
          cooperativeGestures={narrow}
          // The style is parsed well before every tile has arrived (seconds on a slow link): frame
          // the route then instead of waiting for `load`. Later `styledata` events are ignored.
          onStyleData={(e) => !ready && onMapReady(e.target)}
          onLoad={(e) => {
            onMapReady(e.target)
            setTilesLoaded(true)
          }}
          // `load` alone sometimes leaves the pill up in Chromium: any tiles-drawn signal clears it.
          onIdle={(e) => {
            onMapReady(e.target)
            if (!tilesLoaded && tilesDrawn(e)) setTilesLoaded(true)
          }}
          onSourceData={(e) => {
            if (!tilesLoaded && tilesDrawn(e)) setTilesLoaded(true)
          }}
          onZoomEnd={(e) => setView({ map: e.target, zoom: e.viewState.zoom })}
          onError={(e) => {
            const fail = mapFailureOf(e)
            if (fail) setFailure(fail)
            else console.warn('[map]', e.error)
          }}
          onClick={() => {
            setHovered(null)
            setPinned(null)
            onSelectStop(null)
          }}
          style={{ width: '100%', height: '100%' }}
        >
          <NavigationControl position="top-right" showCompass={false} />
          <ScaleControl position="bottom-right" unit="imperial" maxWidth={90} />
          <AttributionControl position="bottom-right" compact />

          {routeData && (
            <Source id="route" type="geojson" data={routeData}>
              <Layer {...ROUTE_CASING} />
              <Layer {...ROUTE_LEG0} />
              <Layer {...ROUTE_LEG1} />
            </Source>
          )}

          {plan
            ? places.map((place) => (
                <Marker
                  key={place.key}
                  longitude={place.lngLat[0]}
                  latitude={place.lngLat[1]}
                  anchor={place.role ? 'bottom' : 'center'}
                  style={{ zIndex: markerZ(place, place.key === popupKey) }}
                  onClick={(e) => {
                    // Keep the map's own click handler (which clears the selection) from firing.
                    e.originalEvent.stopPropagation()
                    selectPlace(place)
                  }}
                >
                  {place.role ? (
                    <EndpointPin
                      role={place.role}
                      label={place.title}
                      nearby={place.nearby}
                      active={place.key === popupKey}
                      onHover={(on) => setHovered(on ? place.key : null)}
                    />
                  ) : (
                    <StopMarker
                      place={place}
                      active={place.key === popupKey}
                      onHover={(on) => setHovered(on ? place.key : null)}
                    />
                  )}
                </Marker>
              ))
            : preview.map((p) => (
                <Marker key={p.role} longitude={p.lngLat[0]} latitude={p.lngLat[1]} anchor="bottom">
                  <EndpointPin role={p.role} label={p.label} />
                </Marker>
              ))}

          {popupPlace && (
            <Popup
              longitude={popupPlace.lngLat[0]}
              latitude={popupPlace.lngLat[1]}
              // No fixed anchor: MapLibre flips the popup to whichever side fits inside the map.
              offset={popupPlace.role ? PIN_POPUP_OFFSET : 20}
              closeButton={false}
              closeOnClick={false}
              maxWidth="300px"
              focusAfterOpen={false}
            >
              <PlacePopup place={popupPlace} homeTzAbbr={plan?.input.home_tz_abbr} />
            </Popup>
          )}
        </MapGL>
      )}

      {!tilesLoaded && !failure && !loading && (
        <p
          role="status"
          className="pointer-events-none absolute bottom-16 left-1/2 z-[5] flex w-max max-w-[calc(100%-2rem)] -translate-x-1/2 items-center gap-2 rounded-2xl bg-white/95 px-3 py-1.5 text-center text-xs font-medium text-ink-600 shadow-card ring-1 ring-ink-900/10"
        >
          {tilesSlow ? (
            'The basemap is slow to load. Your route and stops are shown.'
          ) : (
            <>
              <LoaderCircle className="size-3.5 shrink-0 animate-spin text-ink-400" aria-hidden /> Loading map…
            </>
          )}
        </p>
      )}

      {!plan && !loading && preview.length === 0 && (
        <div className="pointer-events-none absolute inset-x-0 top-4 flex justify-center px-4">
          <div className="pointer-events-auto flex flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-2xl bg-white/90 py-1.5 pr-1.5 pl-3.5 text-xs font-medium text-ink-600 shadow-card ring-1 ring-ink-900/5 backdrop-blur sm:rounded-full">
            <span>Your route, rests and fuel stops will appear here</span>
            {onLoadSample && (
              <button
                type="button"
                onClick={onLoadSample}
                className="inline-flex h-7 items-center gap-1 rounded-full bg-ink-900 px-2.5 text-xs font-semibold text-white hover:bg-ink-800"
              >
                <Sparkles className="size-3.5 text-hw-300" aria-hidden />
                See a sample trip
              </button>
            )}
          </div>
        </div>
      )}

      {loading && (
        <div className="absolute inset-0 grid place-items-center bg-ink-100/40 px-4 backdrop-blur-[1.5px]" role="status">
          <div className="flex max-w-sm items-start gap-3 rounded-xl bg-ink-900 px-4 py-3 text-sm font-medium text-white shadow-pop">
            <LoaderCircle className="mt-0.5 size-4 shrink-0 animate-spin text-hw-400" aria-hidden />
            {slow ? (
              <span>
                Still working.
                <span className="mt-0.5 block text-[13px] font-normal text-ink-300">
                  The free truck router is slow right now; falling back to the backup router if needed…
                </span>
              </span>
            ) : (
              'Routing & scheduling HOS stops…'
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** Shown in place of the map when the browser cannot draw it; the rest of the app still works. */
function MapUnavailable({ failure, plan }: { failure: MapFailure; plan: PlanResponse | null }) {
  const { input } = plan ?? {}
  const names = input && {
    current: placeLabel(input.current_location.label),
    pickup: placeLabel(input.pickup_location.label),
    dropoff: placeLabel(input.dropoff_location.label),
  }
  return (
    <div className="absolute inset-0 grid place-items-center overflow-auto p-4" role="status">
      <div className="w-full max-w-sm rounded-xl bg-white p-4 text-sm shadow-card ring-1 ring-ink-900/10">
        <p className="flex items-center gap-2 font-semibold text-ink-900">
          <MapPinOff className="size-4 shrink-0 text-ink-500" aria-hidden /> The map can't be shown in this browser
        </p>
        <p className="mt-1 text-[13px] leading-snug text-ink-600">
          {failure === 'webgl'
            ? 'It needs WebGL 2, which is turned off or unsupported here (Safari 15 or newer, or any current browser, has it).'
            : 'The map failed to start, which is usually a network hiccup. Reloading the page normally fixes it.'}{' '}
          {plan ? 'The route, stops and daily logs are all in the panel.' : 'Trip planning and the daily logs still work.'}
        </p>
        {plan && names && (
          <ol className="mt-3 grid gap-1.5 border-t border-ink-100 pt-3">
            {plan.route.legs.map((leg, i) => (
              <li key={i} className="flex items-baseline justify-between gap-3 text-[13px]">
                <span className="min-w-0 truncate text-ink-800">
                  {names[leg.from_role]} → {names[leg.to_role]}
                </span>
                <span className="tabular shrink-0 font-mono text-xs text-ink-500">
                  {formatMiles(leg.distance_miles)} · {formatDuration(leg.duration_hours)}
                </span>
              </li>
            ))}
            <li className="text-xs text-ink-500">
              {plan.stops.length} scheduled stops · see the itinerary for times and places
            </li>
          </ol>
        )}
      </div>
    </div>
  )
}
