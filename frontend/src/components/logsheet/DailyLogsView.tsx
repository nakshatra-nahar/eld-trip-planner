// Daily Logs tab: day switcher, "Show all", print/export toolbar, status legend,
// and the FMCSA sheets themselves.

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { FileCode, ImageDown, Layers, Printer } from 'lucide-react'
import type { DailyLog, DutyStatus, LogHeaderDetails } from '../../types/api'
import { LogSheet } from './LogSheet'
import { downloadPng, downloadSvg } from './exporters'
import {
  STATUS_LABELS,
  STATUS_ORDER,
  formatHours,
  minutesByStatus,
  roundedHoursByStatus,
  shortDateLabel,
} from './geometry'
import './logsheet.css'

export interface DailyLogsViewProps {
  logs: DailyLog[]
  header: LogHeaderDetails
  tripLabel?: string
}

const PRINT_CLASS = 'printing-logs'

const STATUS_SHORT: Record<DutyStatus, string> = { OFF: 'Off duty', SB: 'Sleeper', D: 'Driving', ON: 'On duty' }

export function DailyLogsView({ logs, header, tripLabel }: DailyLogsViewProps) {
  const [selected, setSelected] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [printing, setPrinting] = useState(false)
  const [busy, setBusy] = useState<null | 'png'>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const sheetRefs = useRef(new Map<number, SVGSVGElement>())
  const pillRefs = useRef<(HTMLButtonElement | null)[]>([])

  const count = logs.length
  const index = Math.min(selected, Math.max(0, count - 1))
  const current = logs[index]

  // Print: mount every sheet in a body-level portal, flag <body>, print, clean up.
  useEffect(() => {
    if (!printing) return
    document.body.classList.add(PRINT_CLASS)
    const done = () => setPrinting(false)
    window.addEventListener('afterprint', done)
    const frame = requestAnimationFrame(() => {
      window.print()
    })
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('afterprint', done)
      document.body.classList.remove(PRINT_CLASS)
    }
  }, [printing])

  const setSheetRef = useCallback(
    (i: number) => (el: SVGSVGElement | null) => {
      if (el) sheetRefs.current.set(i, el)
      else sheetRefs.current.delete(i)
    },
    [],
  )

  if (!current) {
    return (
      <section className="ls-view">
        <p className="ls-empty">No log sheets yet. Plan a trip to generate the driver's daily logs.</p>
      </section>
    )
  }

  const fileBase = `drivers-daily-log-day-${current.day_number}-${current.date}`
  const exportSvg = () => {
    const svg = sheetRefs.current.get(index)
    if (svg) downloadSvg(svg, `${fileBase}.svg`)
  }
  const exportPng = async () => {
    const svg = sheetRefs.current.get(index)
    if (!svg) return
    setBusy('png')
    setExportError(null)
    try {
      await downloadPng(svg, `${fileBase}.png`, 2)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'PNG export failed')
    } finally {
      setBusy(null)
    }
  }

  const selectDay = (i: number, focus = false) => {
    setSelected(i)
    if (focus) pillRefs.current[i]?.focus()
    if (showAll) {
      sheetRefs.current.get(i)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  const onPillKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const moves: Record<string, number> = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: count - 1 }
    if (!(e.key in moves)) return
    e.preventDefault()
    selectDay((moves[e.key] + count) % count, true)
  }

  // Legend: the selected day, or the whole trip when every sheet is shown.
  const legendLogs = showAll ? logs : [current]
  const legendMinutes = { OFF: 0, SB: 0, D: 0, ON: 0 } as Record<DutyStatus, number>
  for (const lg of legendLogs) {
    const m = minutesByStatus(lg.segments)
    for (const s of STATUS_ORDER) legendMinutes[s] += m[s]
  }
  const legendHours = roundedHoursByStatus(legendMinutes)
  const legendMiles = legendLogs.reduce((a, lg) => a + lg.total_miles, 0)

  const visible = showAll ? logs.map((lg, i) => ({ lg, i })) : [{ lg: current, i: index }]

  return (
    <section className="ls-view" aria-label="Driver's daily logs">
      <div className="ls-toolbar">
        <div className="ls-days">
          <div className="ls-pills" role="tablist" aria-label="Log sheet day" onKeyDown={onPillKey}>
            {logs.map((lg, i) => {
              const active = i === index
              return (
                <button
                  key={lg.date}
                  ref={(el) => {
                    pillRefs.current[i] = el
                  }}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  tabIndex={active ? 0 : -1}
                  className="ls-pill"
                  data-active={active || undefined}
                  onClick={() => selectDay(i)}
                >
                  <span className="ls-pill-day">Day {lg.day_number}</span>
                  <span className="ls-pill-date">{shortDateLabel(lg.date)}</span>
                </button>
              )
            })}
          </div>
          {count > 1 ? (
            <button
              type="button"
              className="ls-toggle"
              aria-pressed={showAll}
              onClick={() => setShowAll((v) => !v)}
            >
              <Layers size={16} aria-hidden />
              <span>Show all</span>
            </button>
          ) : null}
        </div>

        <div className="ls-actions" role="group" aria-label="Print and export">
          <button type="button" className="ls-btn ls-btn-primary" onClick={() => setPrinting(true)}>
            <Printer size={16} aria-hidden />
            <span>Print / Save as PDF</span>
          </button>
          <button type="button" className="ls-btn" onClick={exportSvg} title={`Download day ${current.day_number} as SVG`}>
            <FileCode size={16} aria-hidden />
            <span>SVG</span>
          </button>
          <button
            type="button"
            className="ls-btn"
            onClick={exportPng}
            disabled={busy === 'png'}
            title={`Download day ${current.day_number} as PNG (2x)`}
          >
            <ImageDown size={16} aria-hidden />
            <span>{busy === 'png' ? 'Rendering…' : 'PNG'}</span>
          </button>
        </div>
      </div>

      <div className="ls-legend" aria-label={showAll ? 'Trip totals by duty status' : `Day ${current.day_number} totals by duty status`}>
        <span className="ls-legend-scope">{showAll ? `All ${count} days` : `Day ${current.day_number} of ${count}`}</span>
        {STATUS_ORDER.map((s) => (
          <span key={s} className="ls-legend-item" title={STATUS_LABELS[s]}>
            <span className={`ls-swatch ls-swatch-${s}`} aria-hidden />
            <span className="ls-legend-label">{STATUS_SHORT[s]}</span>
            <span className="ls-legend-value">{formatHours(legendHours[s])} h</span>
          </span>
        ))}
        <span className="ls-legend-item ls-legend-miles">
          <span className="ls-legend-label">Miles</span>
          <span className="ls-legend-value">{Math.round(legendMiles).toLocaleString('en-US')}</span>
        </span>
      </div>
      {exportError ? (
        <p className="ls-error" role="alert">
          {exportError}
        </p>
      ) : null}

      <p className="ls-swipe-hint">Swipe sideways to read the full sheet, or download it as a PNG.</p>

      <div className="ls-sheets">
        {visible.map(({ lg, i }) => (
          <figure key={lg.date} className="ls-sheet" data-selected={i === index || undefined}>
            <LogSheet ref={setSheetRef(i)} log={lg} header={header} dayCount={count} tripLabel={tripLabel} />
          </figure>
        ))}
      </div>

      {printing
        ? createPortal(
            <div className="ls-print-root" aria-hidden>
              {/* @page cannot be scoped by class, so it only exists while printing. */}
              <style>{'@page { size: letter landscape; margin: 0.3in; }'}</style>
              {logs.map((lg) => (
                <div key={lg.date} className="ls-print-page">
                  <LogSheet log={lg} header={header} dayCount={count} tripLabel={tripLabel} />
                </div>
              ))}
            </div>,
            document.body,
          )
        : null}
    </section>
  )
}

export default DailyLogsView
