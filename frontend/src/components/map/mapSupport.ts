// Can this browser draw the MapLibre map at all, and did a map error make it impossible?

/** Without a tiles-drawn event after this long, "Loading map…" turns into a slow-network note. */
export const MAP_LOAD_TIMEOUT_MS = 15_000

/**
 * MapLibre v6 draws with WebGL 2 only (Safari 15+, and every current browser), and its constructor
 * throws when the context cannot be created: WebGL turned off, a blocklisted GPU, or a very old
 * Safari. Checked up front so the map area can say so instead of loading forever.
 */
export function supportsWebGL2(createCanvas: () => HTMLCanvasElement = () => document.createElement('canvas')): boolean {
  try {
    // The probe context is left to GC: losing it explicitly logs "WebGL context was lost" in Firefox.
    return createCanvas().getContext('webgl2') !== null
  } catch {
    return false
  }
}

let cachedSupport: boolean | undefined

/** supportsWebGL2() for this page, probed once. */
export function pageSupportsWebGL2(): boolean {
  cachedSupport ??= supportsWebGL2()
  return cachedSupport
}

export type MapFailure = 'webgl' | 'error'

/**
 * The failure behind a MapLibre `error` event, or null when the map carries on (a missing tile,
 * glyph or sprite). react-map-gl reports errors thrown while creating the map (no WebGL 2 context,
 * the MapLibre chunk failing to download) with no `target`: no map exists, so nothing will draw.
 */
export function mapFailureOf(event: { target?: unknown; error?: unknown }): MapFailure | null {
  const error = event.error as { name?: string; message?: string } | undefined
  const gpu = error?.name === 'GPUInitializationError' || /webgl/i.test(error?.message ?? '')
  if (event.target) return gpu ? 'webgl' : null
  return gpu ? 'webgl' : 'error'
}

/** The parts of a MapLibre `load`, `idle` or `sourcedata` event that say whether tiles are drawn. */
export interface MapDrawEvent {
  type: string
  isSourceLoaded?: boolean
  sourceDataType?: string
  target?: { areTilesLoaded?: () => boolean }
}

/**
 * Has the basemap drawn? MapLibre's `load` fires once, after the first complete render, but in
 * Chromium it can be missed or held back (a slow sprite or glyph request, a tile error), which
 * left "Loading map…" on top of a finished map. `idle` (nothing left to load or animate) and a
 * `sourcedata` event after which every source's visible tiles are loaded mean the same thing,
 * so any of them clears the pill. `sourcedata` for metadata alone (a source added, no tiles) does not.
 */
export function tilesDrawn(event: MapDrawEvent): boolean {
  if (event.type === 'load' || event.type === 'idle') return true
  if (event.type !== 'sourcedata' || event.isSourceLoaded !== true || event.sourceDataType === 'metadata') return false
  return event.target?.areTilesLoaded?.() ?? false
}
