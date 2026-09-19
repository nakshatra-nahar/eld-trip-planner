// Offline ApiClient used with ?demo=1 so the UI can be reviewed without the backend.
// The fixtures are real responses recorded from the live backend (OSRM routing + HOS engine).
import type { ApiClient } from '../lib/api'
import type { GeocodeResult, PlanResponse } from '../types/api'

const CITIES: GeocodeResult[] = [
  ['Chicago', 'Illinois', 'IL', 41.8781, -87.6298],
  ['Joliet', 'Illinois', 'IL', 41.525, -88.0817],
  ['Denver', 'Colorado', 'CO', 39.7392, -104.9903],
  ['Los Angeles', 'California', 'CA', 34.0522, -118.2437],
  ['Long Beach', 'California', 'CA', 33.7701, -118.1937],
  ['Dallas', 'Texas', 'TX', 32.7767, -96.797],
  ['Fort Worth', 'Texas', 'TX', 32.7555, -97.3308],
  ['Houston', 'Texas', 'TX', 29.7604, -95.3698],
  ['Atlanta', 'Georgia', 'GA', 33.749, -84.388],
  ['Kansas City', 'Missouri', 'MO', 39.0997, -94.5786],
  ['St. Louis', 'Missouri', 'MO', 38.627, -90.1994],
  ['Memphis', 'Tennessee', 'TN', 35.1495, -90.049],
  ['Nashville', 'Tennessee', 'TN', 36.1627, -86.7816],
  ['Phoenix', 'Arizona', 'AZ', 33.4484, -112.074],
  ['Salt Lake City', 'Utah', 'UT', 40.7608, -111.891],
  ['Seattle', 'Washington', 'WA', 47.6062, -122.3321],
  ['Newark', 'New Jersey', 'NJ', 40.7357, -74.1724],
  ['New York', 'New York', 'NY', 40.7128, -74.006],
  ['Columbus', 'Ohio', 'OH', 39.9612, -82.9988],
  ['Indianapolis', 'Indiana', 'IN', 39.7684, -86.1581],
  ['Laredo', 'Texas', 'TX', 27.5306, -99.4803],
  ['Toronto', 'Ontario', 'ON', 43.6532, -79.3832],
].map(([city, region, abbr, lat, lon]) => ({
  label: `${city}, ${region}, ${abbr === 'ON' ? 'Canada' : 'United States'}`,
  short_label: `${city}, ${abbr}`,
  lat: lat as number,
  lon: lon as number,
}))

function wait<T>(ms: number, value: T, signal?: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const id = window.setTimeout(() => resolve(value), ms)
    signal?.addEventListener('abort', () => {
      window.clearTimeout(id)
      reject(new DOMException('Aborted', 'AbortError'))
    })
  })
}

export function createDemoClient(plan: PlanResponse): ApiClient {
  return {
    planTrip: (_req, signal) => wait(1100, structuredClone(plan), signal),
    geocode: (query, signal) => {
      const q = query.trim().toLowerCase()
      const results = CITIES.filter((c) => c.label.toLowerCase().includes(q)).slice(0, 6)
      return wait(220, { results }, signal)
    },
    reverse: (lat, lon, signal) => {
      const nearest = CITIES.reduce((best, c) =>
        Math.hypot(c.lat - lat, c.lon - lon) < Math.hypot(best.lat - lat, best.lon - lon) ? c : best,
      )
      return wait(300, { result: { ...nearest, lat, lon } }, signal)
    },
  }
}

/**
 * Loads the recorded fixture selected by ?demo= (each is its own lazy chunk):
 * - `restart`: Seattle, WA -> Denver, CO -> Houston, TX at 60 h used (34-hour restart, 5 sheets)
 * - anything else: Chicago, IL -> St. Louis, MO -> Dallas, TX at 10 h used (2 sheets)
 */
export async function loadDemoPlan(search: string): Promise<PlanResponse> {
  const demo = new URLSearchParams(search).get('demo')
  const mod =
    demo === 'restart' ? await import('./live-seattle-houston.json') : await import('./live-chicago-dallas.json')
  return mod.default as PlanResponse
}
