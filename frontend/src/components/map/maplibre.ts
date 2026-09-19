// maplibre-gl v6 loads its tile worker from a sibling file next to the module, which bundlers do not
// emit. Bundle the worker with Vite (`?worker&url`) and point maplibre at it before the first map.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

let loader: ReturnType<typeof load> | null = null

async function load() {
  const maplibre = await import('maplibre-gl')
  maplibre.setWorkerUrl(workerUrl)
  return maplibre
}

/** Lazily imports maplibre-gl (kept out of the main bundle) with the worker URL configured. */
export function loadMaplibre() {
  loader ??= load()
  return loader
}
