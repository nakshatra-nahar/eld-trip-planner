import { LoaderCircle, LocateFixed } from 'lucide-react'
import { useState } from 'react'
import type { ApiClient } from '../../lib/api'
import { Tooltip } from '../ui'
import type { LocationValue } from './types'

interface UseMyLocationButtonProps {
  client: ApiClient
  onLocated: (value: LocationValue) => void
  onError: (message: string) => void
}

const GEO_ERRORS: Record<number, string> = {
  1: 'Location permission was denied. Type your location instead.',
  2: 'Your position is unavailable right now. Type your location instead.',
  3: 'Finding your position timed out. Try again or type your location.',
}

/** Fills the field from navigator.geolocation, named via the offline reverse geocoder. */
export function UseMyLocationButton({ client, onLocated, onError }: UseMyLocationButtonProps) {
  const [busy, setBusy] = useState(false)

  if (typeof navigator === 'undefined' || !('geolocation' in navigator)) return null

  function locate() {
    setBusy(true)
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        const { latitude: lat, longitude: lon } = coords
        const fallback = `${lat.toFixed(4)}, ${lon.toFixed(4)}`
        try {
          const { result } = await client.reverse(lat, lon)
          const label = result?.short_label || fallback
          onLocated({ text: label, selected: { label: result?.label ?? label, short_label: label, lat, lon } })
        } catch {
          // Coordinates are all the planner needs; the name is cosmetic.
          onLocated({ text: fallback, selected: { label: fallback, short_label: fallback, lat, lon } })
        } finally {
          setBusy(false)
        }
      },
      (err) => {
        setBusy(false)
        onError(GEO_ERRORS[err.code] ?? 'Could not get your location.')
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    )
  }

  return (
    <Tooltip content="Use my location" side="top" align="end">
      <button
        type="button"
        onClick={locate}
        disabled={busy}
        aria-label="Use my location"
        className="grid size-9 place-items-center rounded-lg text-hw-600 hover:bg-hw-50 disabled:text-ink-400"
      >
        {busy ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <LocateFixed className="size-4" aria-hidden />}
      </button>
    </Tooltip>
  )
}
