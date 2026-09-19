import 'maplibre-gl/dist/maplibre-gl.css'
import { LoaderCircle, Maximize2 } from 'lucide-react'
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
import type { Offset as PopupOffset, StyleSpecification } from 'maplibre-gl'
import type { LngLat, PlanResponse } from '../../types/api'
import { loadMaplibre } from './maplibre'
import { loadMapStyle } from './mapStyle'
import { MapLegend } from './MapLegend'
import { EndpointPin, StopMarker } from './markers'
import {
  type Bounds,
  boundsOf,
  buildPlaces,
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

export function TripMap({ plan, preview, focus, selectedStopId, onSelectStop, loading }: TripMapProps) {
  const mapRef = useRef<MapRef>(null)
  const [loaded, setLoaded] = useState(false)
  const [mapStyle, setMapStyle] = useState<StyleSpecification | string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [pinned, setPinned] = useState<string | null>(null)
  const narrow = useIsNarrow()
  const [legendOpen, setLegendOpen] = useState(() => !window.matchMedia('(max-width: 640px)').matches)

  useEffect(() => {
    let cancelled = false
    loadMapStyle().then((style) => !cancelled && setMapStyle(style))
    return () => {
      cancelled = true
    }
  }, [])

  const places = useMemo(() => (plan ? buildPlaces(plan) : []), [plan])
  const routeData = useMemo(() => (plan ? routeFeatures(plan) : null), [plan])
  const routeBounds = useMemo(() => (plan ? boundsOf(plan.route.geometry) : null), [plan])

  // Extra left padding on wide maps keeps the route clear of the legend.
  const padding = useMemo(
    () => (narrow ? { top: 64, bottom: 84, left: 40, right: 56 } : { top: 72, bottom: 56, left: 220, right: 72 }),
    [narrow],
  )

  const fit = useCallback(
    (bounds: Bounds | null, duration = 900) => {
      const map = mapRef.current
      if (!map || !bounds) return
      // A hidden or collapsed container cannot fit the padded bounds (MapLibre warns and bails).
      const el = map.getContainer()
      if (el.clientWidth <= padding.left + padding.right || el.clientHeight <= padding.top + padding.bottom) return
      map.fitBounds(bounds, { padding, duration, maxZoom: 11 })
    },
    [padding],
  )

  // Frame the route whenever a new plan arrives.
  useEffect(() => {
    if (loaded && routeBounds) fit(routeBounds)
  }, [loaded, routeBounds, fit])

  // Before a plan exists, frame the locations picked in the form.
  const hasPlan = plan !== null
  useEffect(() => {
    if (!loaded || hasPlan) return
    if (preview.length >= 2) fit(boundsOf(preview.map((p) => p.lngLat)))
    else if (preview.length === 1) mapRef.current?.flyTo({ center: preview[0].lngLat, zoom: 6, duration: 900 })
  }, [loaded, hasPlan, preview, fit])

  // Fly to itinerary selections.
  useEffect(() => {
    if (!loaded || !focus) return
    const map = mapRef.current
    if (!map) return
    if (focus.bounds) {
      fit(focus.bounds, 1000)
    } else if (focus.lngLat) {
      map.flyTo({ center: focus.lngLat, zoom: Math.max(map.getZoom(), 8), duration: 1100, essential: true })
    }
  }, [focus, loaded, fit])

  const selectedPlaceKey = useMemo(
    () => (selectedStopId ? (places.find((p) => p.stops.some((s) => s.id === selectedStopId))?.key ?? null) : null),
    [places, selectedStopId],
  )
  const popupKey = hovered ?? pinned ?? selectedPlaceKey
  const popupPlace = places.find((p) => p.key === popupKey) ?? null

  function selectPlace(place: MapPlace) {
    setPinned(place.key)
    // On phones the legend would cover the popup: fold it away while a place is open.
    if (narrow) setLegendOpen(false)
    onSelectStop(place.stops[0]?.id ?? null)
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#eef0f3]">
      {/* Map controls come first in the DOM so they are first in tab order (they sit top-left),
          and stack above markers (z 1-3) but below an open popup (z 5). */}
      {plan && (
        <button
          type="button"
          onClick={() => fit(routeBounds)}
          className="absolute top-2.5 left-2.5 z-[4] inline-flex h-9 items-center gap-1.5 rounded-[10px] bg-white px-3 text-[13px] font-medium text-ink-800 shadow-card ring-1 ring-ink-900/10 hover:bg-ink-50"
        >
          <Maximize2 className="size-3.5" aria-hidden /> Fit route
        </button>
      )}
      {plan && <MapLegend plan={plan} open={legendOpen} onToggle={() => setLegendOpen((o) => !o)} />}

      {mapStyle && (
        <MapGL
          ref={mapRef}
          mapLib={loadMaplibre()}
          initialViewState={DEFAULT_VIEW}
          mapStyle={mapStyle}
          attributionControl={false}
          dragRotate={false}
          touchPitch={false}
          cooperativeGestures={narrow}
          onLoad={() => setLoaded(true)}
          onClick={() => {
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
                  style={{ zIndex: place.key === popupKey ? 3 : place.role ? 2 : 1 }}
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
              <PlacePopup place={popupPlace} />
            </Popup>
          )}
        </MapGL>
      )}

      {!plan && !loading && preview.length === 0 && (
        <div className="pointer-events-none absolute inset-x-0 top-4 flex justify-center px-4">
          <p className="rounded-full bg-white/90 px-3.5 py-1.5 text-xs font-medium text-ink-600 shadow-card ring-1 ring-ink-900/5 backdrop-blur">
            Your route, rests and fuel stops will appear here
          </p>
        </div>
      )}

      {loading && (
        <div className="absolute inset-0 grid place-items-center bg-ink-100/40 backdrop-blur-[1.5px]" role="status">
          <div className="flex items-center gap-3 rounded-xl bg-ink-900 px-4 py-3 text-sm font-medium text-white shadow-pop">
            <LoaderCircle className="size-4 animate-spin text-hw-400" aria-hidden />
            Routing &amp; scheduling HOS stops…
          </div>
        </div>
      )}
    </div>
  )
}
