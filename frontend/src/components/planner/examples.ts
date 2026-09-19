import { fromResolved, type PlannerValues } from './types'

export interface ExampleTrip {
  id: string
  title: string
  detail: string
  values: Pick<PlannerValues, 'current' | 'pickup' | 'dropoff' | 'cycleUsed'>
}

/** Realistic preset trips with coordinates, so they plan without a geocoding round-trip. */
export const EXAMPLE_TRIPS: ExampleTrip[] = [
  {
    id: 'short',
    title: 'Short haul',
    detail: 'Dallas → Fort Worth → Houston · 10 h used',
    values: {
      current: fromResolved('Dallas, TX', 32.7767, -96.797),
      pickup: fromResolved('Fort Worth, TX', 32.7555, -97.3308),
      dropoff: fromResolved('Houston, TX', 29.7604, -95.3698),
      cycleUsed: '10',
    },
  },
  {
    id: 'cross',
    title: 'Cross-country',
    detail: 'Chicago → Denver → Los Angeles · 22 h used',
    values: {
      current: fromResolved('Chicago, IL', 41.8781, -87.6298),
      pickup: fromResolved('Denver, CO', 39.7392, -104.9903),
      dropoff: fromResolved('Los Angeles, CA', 34.0522, -118.2437),
      cycleUsed: '22',
    },
  },
  {
    id: 'cycle',
    title: 'Near cycle limit',
    detail: 'Kansas City → St. Louis → Atlanta · 64 h used',
    values: {
      current: fromResolved('Kansas City, MO', 39.0997, -94.5786),
      pickup: fromResolved('St. Louis, MO', 38.627, -90.1994),
      dropoff: fromResolved('Atlanta, GA', 33.749, -84.388),
      cycleUsed: '64',
    },
  },
]
