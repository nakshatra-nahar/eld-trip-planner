// Local (stop) time vs. home-terminal time. The API sends both for every event and stop; the
// logs stay on home-terminal time, and local times are shown only where they differ.
import { formatClock } from './format'

/** "19:14 EDT local" when the local wall-clock time differs from the home-terminal one, else null. */
export function localTimeNote(home: string, local?: string, abbr?: string): string | null {
  if (!local || local === home) return null
  return `${formatClock(local)}${abbr ? ` ${abbr}` : ''} local`
}

/** "18:14 CDT" (the abbreviation is omitted when unknown). */
export function homeClock(home: string, abbr?: string): string {
  return `${formatClock(home)}${abbr ? ` ${abbr}` : ''}`
}

/** Typical receiving docks are closed 22:00-05:00 local time. */
export function outsideDockHours(localStart: string): boolean {
  const hour = Number(localStart.slice(11, 13))
  return hour >= 22 || hour < 5
}
