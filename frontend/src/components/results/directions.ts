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

const INTERSTATE = /\bI[\s-]?(\d{1,3})\b/

/** "I-55" when the step is on (or onto) an interstate, else null. */
export function interstateOf(step: Pick<Instruction, 'road' | 'text'>): string | null {
  const m = INTERSTATE.exec(step.road) ?? INTERSTATE.exec(step.text)
  return m ? `I-${m[1]}` : null
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

/**
 * Keeps the highway sequence readable: the departure and arrival stay visible, and the city
 * streets right after departure or right before arrival collapse into one row.
 */
export function groupSteps(steps: readonly Instruction[]): StepItem[] {
  const n = steps.length
  const street = (st: Instruction) => !interstateOf(st) && st.maneuver !== 'depart' && st.maneuver !== 'arrive'
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
