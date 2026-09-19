import { describe, expect, it, vi } from 'vitest'
import { mapFailureOf, supportsWebGL2 } from './mapSupport'

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
