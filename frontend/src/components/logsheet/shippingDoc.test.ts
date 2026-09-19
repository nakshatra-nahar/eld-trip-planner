import { describe, expect, it } from 'vitest'
import { splitShippingDoc } from './geometry'

describe('splitShippingDoc', () => {
  it('splits "number · commodity" onto the manifest and shipper lines', () => {
    expect(splitShippingDoc('Pro No. 101601 · General freight')).toEqual({ manifest: 'Pro No. 101601', shipper: 'General freight' })
  })
  it('keeps the single-value heuristic', () => {
    expect(splitShippingDoc('BOL-10442')).toEqual({ manifest: 'BOL-10442', shipper: '' })
    expect(splitShippingDoc('Acme Foods, frozen produce')).toEqual({ manifest: '', shipper: 'Acme Foods, frozen produce' })
    expect(splitShippingDoc('  ')).toEqual({ manifest: '', shipper: '' })
  })
})
