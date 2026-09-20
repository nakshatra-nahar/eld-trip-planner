import { describe, expect, it, vi } from 'vitest'
import { mapFailureOf, supportsWebGL2, tilesDrawn } from './mapSupport'

const canvasWith = (getContext: () => unknown) => () => ({ getContext }) as unknown as HTMLCanvasElement

describe('supportsWebGL2', () => {
  it('is true when a WebGL 2 context can be created', () => {
    const getContext = vi.fn(() => ({}))
    expect(supportsWebGL2(canvasWith(getContext))).toBe(true)
    expect(getContext).toHaveBeenCalledWith('webgl2')
  })

  it('is false when the browser has no WebGL 2 or throws while creating it', () => {
    expect(supportsWebGL2(canvasWith(() => null))).toBe(false)
    expect(
      supportsWebGL2(
        canvasWith(() => {
          throw new Error('blocked')
        }),
      ),
    ).toBe(false)
  })
})

describe('mapFailureOf', () => {
  const gpuError = Object.assign(new Error('WebGL2 is required to display this map.'), { name: 'GPUInitializationError' })

  it('treats a map that could not be created as failed', () => {
    expect(mapFailureOf({ target: null, error: gpuError })).toBe('webgl')
    expect(mapFailureOf({ target: null, error: new TypeError('Failed to fetch dynamically imported module') })).toBe('error')
  })

  it('lets a running map carry on after a tile, glyph or sprite error', () => {
    const map = {}
    expect(mapFailureOf({ target: map, error: new Error('AJAXError: Not Found (404)') })).toBeNull()
  })

  it('fails a running map whose WebGL context could not be restored', () => {
    expect(mapFailureOf({ target: {}, error: gpuError })).toBe('webgl')
  })
})

describe('tilesDrawn', () => {
  const map = (loaded: boolean) => ({ areTilesLoaded: () => loaded })

  it('clears "Loading map…" on load or idle', () => {
    expect(tilesDrawn({ type: 'load' })).toBe(true)
    expect(tilesDrawn({ type: 'idle', target: map(false) })).toBe(true)
  })

  it('clears it on a sourcedata event once every visible tile has loaded', () => {
    expect(tilesDrawn({ type: 'sourcedata', isSourceLoaded: true, sourceDataType: 'content', target: map(true) })).toBe(true)
  })

  it('keeps it while tiles are still arriving, or for metadata alone', () => {
    expect(tilesDrawn({ type: 'sourcedata', isSourceLoaded: true, target: map(false) })).toBe(false)
    expect(tilesDrawn({ type: 'sourcedata', isSourceLoaded: false, target: map(true) })).toBe(false)
    expect(tilesDrawn({ type: 'sourcedata', isSourceLoaded: true, sourceDataType: 'metadata', target: map(true) })).toBe(false)
    expect(tilesDrawn({ type: 'styledata', target: map(true) })).toBe(false)
  })
})
