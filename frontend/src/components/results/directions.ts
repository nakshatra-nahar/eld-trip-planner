// Pure helpers for the Directions tab (unit-tested in directions.test.ts).
import { placeLabel } from '../../lib/format'
import type { Instruction } from '../../types/api'

/**
 * Non-interstate steps between the departure and the first interstate (and between the last
 * interstate and the arrival) fold into one "Local streets" row when the run is at least this
 * many steps and no longer than LOCAL_RUN_MILES; otherwise only its sub-half-mile steps fold.
 */
const MIN_LOCAL_RUN = 3
const LOCAL_RUN_MILES = 10
const SHORT_STEP_MILES = 0.5

export type StepItem = { kind: 'step'; step: Instruction } | { kind: 'local'; steps: Instruction[] }

const INTERSTATE = /\b(?:I|Interstate)[\s-]?(\d{1,3}[A-Z]?)\b/

/**
 * "I-55" when the step itself is on an interstate, else null. Only the step's own road counts:
 * the instruction text also names roads the step merely points at ("Keep right toward I 5" on
 * US 101), which must not get a shield.
 */
export function interstateOf(step: Pick<Instruction, 'road'>): string | null {
  const m = INTERSTATE.exec(step.road)
  return m ? `I-${m[1]}` : null
}

/**
 * True when the step is on an interstate or takes one ("Take the I 94 East exit", "Merge onto
 * I-80 W"), ignoring the "toward ..." destination sign. Marks the end of a leading city-street run.
 */
function reachesInterstate(step: Pick<Instruction, 'road' | 'text'>): boolean {
  return interstateOf(step) !== null || INTERSTATE.test(step.text.replace(/\btoward\b.*$/i, ''))
}

/**
 * The road name shown under an instruction, or null when it adds nothing: the instruction
 * already names it, the step arrives, or the road is just the interstate on the shield ("I-55 S").
 */
export function roadCaption(step: Pick<Instruction, 'road' | 'text' | 'maneuver'>): string | null {
  const road = placeLabel(step.road)
  if (!road || step.maneuver === 'arrive') return null
  if (placeLabel(step.text).toLowerCase().includes(road.toLowerCase())) return null
  const shield = interstateOf(step)
  const parts = road.split(/[;,/]/).map((part) => part.trim().replace(/\s+[NSEW]$/, ''))
  if (shield && parts.every((part) => part === shield)) return null
  return road
}

/** Steps this close together that make the same move onto the same road read as one. */
const REPEAT_MILES = 0.5

const sameText = (a: Instruction, b: Instruction) => placeLabel(a.text).toLowerCase() === placeLabel(b.text).toLowerCase()
const sameMove = (a: Instruction, b: Instruction) =>
  a.maneuver === b.maneuver &&
  a.modifier === b.modifier &&
  placeLabel(a.road) !== '' &&
  placeLabel(a.road).toLowerCase() === placeLabel(b.road).toLowerCase() &&
  a.distance_miles <= REPEAT_MILES

/**
 * Collapses consecutive near-duplicate instructions into one row with their summed distance and
 * time: the same text ("Keep left to stay on I-25 South" at every fork of a long run), or the same
 * maneuver onto the same road within REPEAT_MILES. The first step's text is kept (it has the
 * "toward ..." sign); departures and arrivals are never merged.
 */
export function mergeRepeatedSteps(steps: readonly Instruction[]): Instruction[] {
  const out: Instruction[] = []
  for (const step of steps) {
    const prev = out[out.length - 1]
    const fixed = (st: Instruction) => st.maneuver === 'depart' || st.maneuver === 'arrive'
    if (prev && !fixed(prev) && !fixed(step) && (sameText(prev, step) || sameMove(prev, step))) {
      out[out.length - 1] = {
        ...prev,
        road: prev.road || step.road,
        distance_miles: Math.round((prev.distance_miles + step.distance_miles) * 100) / 100,
        duration_minutes: Math.round((prev.duration_minutes + step.duration_minutes) * 10) / 10,
      }
    } else {
      out.push(step)
    }
  }
  return out
}

/**
 * Keeps the highway sequence readable: the departure and arrival stay visible, and the city
 * streets right after departure or right before arrival collapse into one row.
 */
export function groupSteps(steps: readonly Instruction[]): StepItem[] {
  const n = steps.length
  const street = (st: Instruction) => !reachesInterstate(st) && st.maneuver !== 'depart' && st.maneuver !== 'arrive'
  const miles = (from: number, to: number) => steps.slice(from, to).reduce((a, st) => a + st.distance_miles, 0)
  const head = steps[0]?.maneuver === 'depart' ? 1 : 0
  const tail = n - (n > head && steps[n - 1].maneuver === 'arrive' ? 1 : 0)

  let lead = head
  while (lead < tail && street(steps[lead])) lead++
  if (lead === tail) return steps.map((step) => ({ kind: 'step', step })) // no interstate: nothing to fold toward
  if (miles(head, lead) > LOCAL_RUN_MILES) {
    lead = head
    while (lead < tail && street(steps[lead]) && steps[lead].distance_miles < SHORT_STEP_MILES) lead++
  }
  let trail = tail
  while (trail > lead && street(steps[trail - 1])) trail--
  if (miles(trail, tail) > LOCAL_RUN_MILES) {
    trail = tail
    while (trail > lead && street(steps[trail - 1]) && steps[trail - 1].distance_miles < SHORT_STEP_MILES) trail--
  }

  const items: StepItem[] = []
  const pushSteps = (from: number, to: number) => {
    for (const step of steps.slice(from, to)) items.push({ kind: 'step', step })
  }
  const pushRun = (from: number, to: number) => {
    if (to - from >= MIN_LOCAL_RUN) items.push({ kind: 'local', steps: steps.slice(from, to) })
    else pushSteps(from, to)
  }
  pushSteps(0, head)
  pushRun(head, lead)
  pushSteps(lead, trail)
  pushRun(trail, tail)
  pushSteps(tail, n)
  return items
}
