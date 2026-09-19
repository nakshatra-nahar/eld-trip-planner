// Print layout for the whole trip: every sheet, one per landscape page. It stays mounted
// (hidden on screen) while a plan is shown, so the toolbar's Print button and a plain Ctrl+P
// / browser menu print produce the same output.

import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { DailyLog, LogHeaderDetails } from '../../types/api'
import { LogSheet } from './LogSheet'

const PRINT_CLASS = 'printing-logs'

export interface PrintLogsProps {
  logs: DailyLog[]
  header: LogHeaderDetails
  tripLabel?: string
  /** Per-date note printed on the sheet (see lib/dutyPeriods). */
  notes?: ReadonlyMap<string, string | null>
  /** Home-terminal time zone abbreviation the sheets are drawn in, e.g. "CDT". */
  tzAbbr?: string
}

export function PrintLogs({ logs, header, tripLabel, notes, tzAbbr }: PrintLogsProps) {
  useEffect(() => {
    document.body.classList.add(PRINT_CLASS)
    return () => document.body.classList.remove(PRINT_CLASS)
  }, [])

  return createPortal(
    <div className="ls-print-root" aria-hidden>
      {/* @page cannot be scoped by class; this only exists while a plan is on screen. */}
      <style>{'@page { size: letter landscape; margin: 0.3in; }'}</style>
      {logs.map((lg) => (
        <div key={lg.date} className="ls-print-page">
          <LogSheet log={lg} header={header} dayCount={logs.length} tripLabel={tripLabel} note={notes?.get(lg.date)} tzAbbr={tzAbbr} />
        </div>
      ))}
    </div>,
    document.body,
  )
}
