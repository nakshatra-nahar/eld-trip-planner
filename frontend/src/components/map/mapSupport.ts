// Can this browser draw the MapLibre map at all, and did a map error make it impossible?

/** Without a map `load` event after this long, "Loading map…" turns into a slow-network note. */
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
