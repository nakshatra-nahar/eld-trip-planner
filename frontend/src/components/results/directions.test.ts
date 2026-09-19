import { describe, expect, it } from 'vitest'
import type { Instruction } from '../../types/api'
import { groupSteps, interstateOf, roadCaption } from './directions'

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
  it("reads the shield from the step's own road", () => {
    expect(interstateOf({ road: 'I 55' })).toBe('I-55')
    expect(interstateOf({ road: 'I-80 W' })).toBe('I-80')
    expect(interstateOf({ road: 'Interstate 10' })).toBe('I-10')
    expect(interstateOf({ road: 'US 66' })).toBeNull()
    expect(interstateOf({ road: '' })).toBeNull()
  })

  it('ignores interstates named only in the instruction text', () => {
    const toward = step('fork', 'Keep right toward I 5', 'US 101', 12)
    expect(interstateOf(toward)).toBeNull()
    expect(interstateOf(step('off ramp', 'Take the I 94 East exit toward Indiana', '', 0.5))).toBeNull()
    expect(roadCaption(toward)).toBe('US 101')
  })
})

describe('groupSteps with ramps', () => {
  it('stops the local-streets run at a ramp onto an interstate, even when the ramp has no road', () => {
    const items = groupSteps([
      step('depart', 'Head south on Federal St', 'Federal St', 0.1),
      step('turn', 'Turn right onto Van Buren St', 'Van Buren St', 0.2),
      step('turn', 'Turn left onto Wells St', 'Wells St', 0.1),
      step('turn', 'Turn right onto Congress Pkwy', 'Congress Pkwy', 0.4),
      step('off ramp', 'Take the I 94 East exit toward Indiana', '', 0.5),
      step('fork', 'Keep left to take I 94 East', 'I 94', 20),
      step('arrive', 'Arrive', '', 0),
    ])
    expect(items.map((i) => (i.kind === 'local' ? `local:${i.steps.length}` : i.step.maneuver))).toEqual([
      'depart',
      'local:3',
      'off ramp',
      'fork',
      'arrive',
    ])
  })

  it('does not end the run at a street step that only points toward an interstate', () => {
    const items = groupSteps([
      step('depart', 'Head north on Main St', 'Main St', 0.1),
      step('turn', 'Turn left onto 1st Ave toward I 5', '1st Ave', 0.2),
      step('turn', 'Turn right onto Pine St', 'Pine St', 0.1),
      step('turn', 'Turn right onto 4th Ave', '4th Ave', 0.3),
      step('on ramp', 'Take the ramp onto I 5 S', 'I 5', 40),
      step('arrive', 'Arrive', '', 0),
    ])
    expect(items.map((i) => i.kind)).toEqual(['step', 'local', 'step', 'step'])
  })
})

describe('roadCaption', () => {
  it('hides the road when the interstate shield already shows it', () => {
    expect(roadCaption(step('continue', 'Continue', 'I 55', 10))).toBeNull()
    expect(roadCaption(step('continue', 'Keep left', 'I-55 S', 10))).toBeNull()
    expect(roadCaption(step('continue', 'Keep left', 'I 55; I 44', 10))).toBe('I-55; I-44')
  })
  it('hides it when the text names it, and on arrival', () => {
    expect(roadCaption(step('turn', 'Turn left onto Main St', 'Main St', 1))).toBeNull()
    expect(roadCaption(step('arrive', 'Arrive', 'Main St', 0))).toBeNull()
  })
  it('keeps a road the instruction does not mention', () => {
    expect(roadCaption(step('fork', 'Keep right at the fork', 'US 287', 1))).toBe('US 287')
  })
})
