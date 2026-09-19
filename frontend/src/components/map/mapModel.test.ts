import { describe, expect, it } from 'vitest'
import { nudgeFromPin } from './mapModel'

describe('nudgeFromPin', () => {
  it('leaves markers that are clear of the pin alone', () => {
    expect(nudgeFromPin([200, 100], [100, 100])).toBeNull()
    expect(nudgeFromPin([100, 150], [100, 100])).toBeNull()
  })

  it('slides a marker on top of the pin to the right, clear of it', () => {
    expect(nudgeFromPin([100, 100], [100, 100])).toEqual([37, 0])
    expect(nudgeFromPin([105, 80], [100, 100])).toEqual([32, 0])
  })

  it('slides a marker left of the pin further left', () => {
    expect(nudgeFromPin([90, 90], [100, 100])).toEqual([-27, 0])
  })

  it('treats ~20 px from the pin outline as too close', () => {
    expect(nudgeFromPin([100 + 17 + 15, 90], [100, 100])).not.toBeNull()
    expect(nudgeFromPin([100 + 17 + 21, 90], [100, 100])).toBeNull()
  })
})
