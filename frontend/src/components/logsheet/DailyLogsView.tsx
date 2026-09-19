// Daily Logs tab: day switcher, "Show all", print/export toolbar, status legend,
// and the FMCSA sheets themselves.

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { ChevronDown, Download, FileCode, ImageDown, Layers, Printer } from 'lucide-react'
import { formatDuration } from '../../lib/format'
import { scrollBehavior } from '../../lib/motion'
import type { DailyLog, DutyStatus, LogHeaderDetails } from '../../types/api'
import { LogSheet } from './LogSheet'
import { downloadPng, downloadSvg } from './exporters'
import { STATUS_LABELS, STATUS_ORDER, minutesByStatus, roundedMinutesByStatus, shortDateLabel } from './geometry'
import './logsheet.css'

export interface DailyLogsViewProps {
  logs: DailyLog[]
  header: LogHeaderDetails
  tripLabel?: string
  /** Per-date note printed on the sheet (see lib/dutyPeriods). */
  notes?: ReadonlyMap<string, string | null>
  /** Home-terminal time zone abbreviation the sheets are drawn in, e.g. "CDT". */
  tzAbbr?: string
}

const STATUS_SHORT: Record<DutyStatus, string> = { OFF: 'Off duty', SB: 'Sleeper', D: 'Driving', ON: 'On duty' }

export function DailyLogsView({ logs, header, tripLabel, notes, tzAbbr }: DailyLogsViewProps) {
  const [selected, setSelected] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [busy, setBusy] = useState<null | 'png'>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  // Phones: show the whole sheet at once (like the paper form) unless the driver zooms in.
  const [fit, setFit] = useState(true)
  const menuRef = useRef<HTMLDetailsElement>(null)
  const sheetRefs = useRef(new Map<number, SVGSVGElement>())
  const pillRefs = useRef<(HTMLButtonElement | null)[]>([])
  const pillsRef = useRef<HTMLDivElement>(null)

  const count = logs.length
  const index = Math.min(selected, Math.max(0, count - 1))
  const current = logs[index]

  const setSheetRef = useCallback(
    (i: number) => (el: SVGSVGElement | null) => {
      if (el) sheetRefs.current.set(i, el)
      else sheetRefs.current.delete(i)
    },
    [],
  )

  // Close the download menu on an outside click or Escape.
  useEffect(() => {
    const close = (e: Event) => {
      const menu = menuRef.current
      if (!menu?.open) return
      if (e instanceof globalThis.KeyboardEvent ? e.key === 'Escape' : !menu.contains(e.target as Node)) {
        menu.removeAttribute('open')
      }
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', close)
    }
  }, [])

  // Day pills that overflow (phones, long trips) fade at the right edge, so the hidden days
  // read as "scroll for more", and the fade drops once the list is scrolled to its end.
  useEffect(() => {
    const el = pillsRef.current
    if (!el) return
    const update = () => {
      const overflow = el.scrollWidth - el.clientWidth > 1
      const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1
      if (overflow && !atEnd) el.dataset.overflow = ''
      else delete el.dataset.overflow
    }
    update()
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update)
    ro?.observe(el)
    el.addEventListener('scroll', update, { passive: true })
    return () => {
      ro?.disconnect()
      el.removeEventListener('scroll', update)
    }
  }, [count])

  // Keep the selected day's pill visible inside the scrolling pill list. Scrolls only the list
  // (scrollIntoView would also scroll the page to a list that is below the fold).
  useEffect(() => {
    const list = pillsRef.current
    const pill = pillRefs.current[index]
    if (!list || !pill) return
    const left = pill.offsetLeft - list.offsetLeft
    const right = left + pill.offsetWidth
    if (left < list.scrollLeft) list.scrollTo({ left: left - 4, behavior: scrollBehavior() })
    else if (right > list.scrollLeft + list.clientWidth) {
      list.scrollTo({ left: right - list.clientWidth + 4, behavior: scrollBehavior() })
    }
  }, [index])

  if (!current) {
    return (
      <section className="ls-view">
        <p className="ls-empty">No log sheets yet. Plan a trip to generate the driver's daily logs.</p>
      </section>
    )
  }

  const fileBase = `drivers-daily-log-day-${current.day_number}-${current.date}`
  const closeMenu = () => menuRef.current?.removeAttribute('open')
  const exportSvg = async () => {
    closeMenu()
    const svg = sheetRefs.current.get(index)
    if (!svg) return
    setExportError(null)
    try {
      await downloadSvg(svg, `${fileBase}.svg`)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'SVG export failed')
    }
  }
  const exportPng = async () => {
    closeMenu()
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
      sheetRefs.current.get(i)?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
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
  const legendRounded = roundedMinutesByStatus(legendMinutes)
  const legendMiles = legendLogs.reduce((a, lg) => a + lg.total_miles, 0)

  const visible = showAll ? logs.map((lg, i) => ({ lg, i })) : [{ lg: current, i: index }]

  return (
    <section className="ls-view" aria-label="Driver's daily logs">
      <div className="ls-toolbar">
        <div className="ls-days">
          <div ref={pillsRef} className="ls-pills" role="tablist" aria-label="Log sheet day" onKeyDown={onPillKey}>
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
              aria-label="Show all days"
              title="Show every day's sheet"
              onClick={() => setShowAll((v) => !v)}
            >
              <Layers size={16} aria-hidden />
              <span className="ls-toggle-text">Show all</span>
            </button>
          ) : null}
        </div>

        <div className="ls-actions" role="group" aria-label="Print and export">
          <button type="button" className="ls-btn ls-btn-primary" aria-label="Print or save as PDF" onClick={() => window.print()}>
            <Printer size={16} aria-hidden />
            <span>Print / Save as PDF</span>
          </button>
          <details className="ls-menu" ref={menuRef}>
            <summary className="ls-btn" aria-label={`Download day ${current.day_number}`}>
              <Download size={16} aria-hidden />
              <span>{busy === 'png' ? 'Rendering…' : 'Download'}</span>
              <ChevronDown size={14} aria-hidden className="ls-menu-chevron" />
            </summary>
            <div className="ls-menu-list">
              <button type="button" className="ls-menu-item" onClick={exportPng} disabled={busy === 'png'}>
                <ImageDown size={16} aria-hidden />
                <span>
                  PNG image<small>Day {current.day_number}, 2x resolution</small>
                </span>
              </button>
              <button type="button" className="ls-menu-item" onClick={exportSvg}>
                <FileCode size={16} aria-hidden />
                <span>
                  SVG vector<small>Day {current.day_number}, scales to any size</small>
                </span>
              </button>
            </div>
          </details>
        </div>
      </div>

      <div className="ls-legend" aria-label={showAll ? 'Trip totals by duty status' : `Day ${current.day_number} totals by duty status`}>
        <span className="ls-legend-scope">{showAll ? `All ${count} days` : `Day ${current.day_number} of ${count}`}</span>
        {STATUS_ORDER.map((s) => (
          <span key={s} className="ls-legend-item" title={STATUS_LABELS[s]}>
            <span className={`ls-swatch ls-swatch-${s}`} aria-hidden />
            <span className="ls-legend-label">{STATUS_SHORT[s]}</span>
            <span className="ls-legend-value">{formatDuration(legendRounded[s] / 60)}</span>
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

      <div className="ls-zoom" role="group" aria-label="Sheet size">
        <button type="button" aria-pressed={fit} onClick={() => setFit(true)}>
          Fit width
        </button>
        <button type="button" aria-pressed={!fit} onClick={() => setFit(false)}>
          Actual size
        </button>
        <p className="ls-swipe-hint">
          {fit ? 'Tip: tap Actual size or turn your phone sideways to read the sheet.' : 'Swipe sideways to read the full sheet.'}
        </p>
      </div>

      <div className="ls-sheets" data-fit={fit || undefined}>
        {visible.map(({ lg, i }) => (
          <figure key={lg.date} className="ls-sheet" data-selected={i === index || undefined}>
            <LogSheet
              ref={setSheetRef(i)}
              log={lg}
              header={header}
              dayCount={count}
              tripLabel={tripLabel}
              note={notes?.get(lg.date)}
              tzAbbr={tzAbbr}
              tint
            />
          </figure>
        ))}
      </div>

    </section>
  )
}

export default DailyLogsView
