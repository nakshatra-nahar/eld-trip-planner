// Loads the OpenFreeMap basemap style and adapts it for a US trucking map.
import type { StyleSpecification } from 'maplibre-gl'

export const MAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'

/** Latin label, falling back to the English and then the local name. */
const LATIN_LABEL = ['coalesce', ['get', 'name:latin'], ['get', 'name_en'], ['get', 'name']]

type Expr = unknown

/** Swaps every `['get', key]` for `['coalesce', ['get', key], fallback]` inside an expression. */
function defaultGet(expr: Expr, key: string, fallback: unknown): Expr {
  if (!Array.isArray(expr)) return expr
  if (expr[0] === 'get' && expr[1] === key && expr.length === 2) return ['coalesce', expr, fallback]
  return expr.map((e) => defaultGet(e, key, fallback))
}

/**
 * The stock labels print "Latin + native script" for places with a non-Latin name. In the US that
 * means Osage/Cherokee syllabics whose glyph ranges OpenFreeMap does not host (404s in the console),
 * so labels are reduced to their Latin form. Boundary filters also compare a sometimes-null
 * `admin_level`, which logs a style warning; default it to 0.
 */
export function adaptStyle(style: StyleSpecification): StyleSpecification {
  return {
    ...style,
    layers: style.layers.map((layer) => {
      let next = layer
      if (
        next.type === 'symbol' &&
        next.layout?.['text-field'] &&
        JSON.stringify(next.layout['text-field']).includes('name:nonlatin')
      ) {
        next = { ...next, layout: { ...next.layout, 'text-field': LATIN_LABEL as never } }
      }
      if ('filter' in next && next.filter && JSON.stringify(next.filter).includes('"admin_level"')) {
        next = { ...next, filter: defaultGet(next.filter, 'admin_level', 0) as never }
      }
      return next
    }),
  }
}

let cached: Promise<StyleSpecification | string> | null = null

/** Fetches and adapts the style once per page; falls back to the raw URL if the fetch fails. */
export function loadMapStyle(): Promise<StyleSpecification | string> {
  cached ??= fetch(MAP_STYLE_URL)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`style ${r.status}`))))
    .then((style: StyleSpecification) => adaptStyle(style))
    .catch(() => MAP_STYLE_URL)
  return cached
}
