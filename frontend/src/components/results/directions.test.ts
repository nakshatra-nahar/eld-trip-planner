import { describe, expect, it } from 'vitest'
import type { Instruction } from '../../types/api'
import { groupSteps, interstateOf } from './directions'

const step = (maneuver: string, text: string, road: string, distance_miles: number): Instruction => ({
  text,
  maneuver,
  modifier: '',
  road,
  distance_miles,
  duration_minutes: distance_miles,
  location: [0, 0],
})

describe('groupSteps', () => {
  const steps = [
    step('depart', 'Head east on Harrison St', 'Harrison St', 0.1),
    step('turn', 'Turn right onto Clark St', 'Clark St', 0.2),
    step('turn', 'Turn left onto Polk St', 'Polk St', 0.1),
    step('turn', 'Turn right onto Wells St', 'Wells St', 0.3),
    step('on ramp', 'Take the ramp onto I 55 S', 'I 55', 280),
    step('off ramp', 'Take exit 40', 'Exit 40', 0.4),
    step('arrive', 'Arrive at destination', '', 0),
  ]

  it('folds the leading run of short city steps and keeps departure, interstate and arrival visible', () => {
    const items = groupSteps(steps)
    expect(items.map((i) => i.kind)).toEqual(['step', 'local', 'step', 'step', 'step'])
    const local = items[1]
    expect(local.kind === 'local' && local.steps).toHaveLength(3)
  })

  it('folds a run that includes a longer city street, up to the first interstate', () => {
    const items = groupSteps([steps[0], steps[1], step('turn', 'Turn left onto State St', 'State St', 1.2), steps[2], ...steps.slice(4)])
    expect(items.map((i) => i.kind)).toEqual(['step', 'local', 'step', 'step', 'step'])
  })

  it('does not fold a route with no interstate', () => {
    expect(groupSteps([steps[0], steps[1], steps[2], steps[3], steps[6]]).every((i) => i.kind === 'step')).toBe(true)
  })

  it('leaves short runs alone', () => {
    const items = groupSteps([steps[0], steps[1], steps[4], steps[6]])
    expect(items.every((i) => i.kind === 'step')).toBe(true)
  })
})

describe('interstateOf', () => {
  it('finds interstates in the road or the instruction', () => {
    expect(interstateOf({ road: 'I 55', text: '' })).toBe('I-55')
    expect(interstateOf({ road: '', text: 'Merge onto I-80 W' })).toBe('I-80')
    expect(interstateOf({ road: 'US 66', text: 'Continue on US 66' })).toBeNull()
  })
})
