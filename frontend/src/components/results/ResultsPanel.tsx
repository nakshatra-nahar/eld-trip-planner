import { CalendarDays, ListOrdered, Signpost } from 'lucide-react'
import { useMemo } from 'react'
import { cn } from '../../lib/cn'
import { dutyPeriodNote } from '../../lib/dutyPeriods'
import { placeLabel } from '../../lib/format'
import type { ResultsTab } from '../../lib/planQuery'
import type { LogHeaderDetails, PlanResponse, TimelineEvent } from '../../types/api'
import { SAMPLE_LOG_HEADER } from '../../hooks/useLogHeader'
import { DailyLogsView, PrintLogs } from '../logsheet'
import { Card, type TabItem, Tabs } from '../ui'
import { DirectionsView } from './DirectionsView'
import { ItineraryView } from './ItineraryView'
import { ShareLinkButton } from './ShareLinkButton'

type TabKey = ResultsTab

interface ResultsPanelProps {
  plan: PlanResponse
  header: LogHeaderDetails
  selectedId: string | null
  onSelectEvent: (event: TimelineEvent) => void
  /** Link that reopens this plan; omitted for the bundled sample. */
  shareUrl?: string
  /** Selected tab, owned by App so it can live in the URL and be set from the trip overview. */
  tab: TabKey
  onTabChange: (tab: TabKey) => void
}

export function ResultsPanel({ plan, header, selectedId, onSelectEvent, shareUrl, tab, onTabChange }: ResultsPanelProps) {
  const { input } = plan
  const tripLabel = [input.current_location, input.pickup_location, input.dropoff_location].map((l) => placeLabel(l.label)).join(' → ')
  // The start location is treated as the home terminal (the logs are drawn in its time zone),
  // so while the header still holds the sample address the sheet names that place instead.
  const sheetHeader = useMemo(
    () =>
      header.home_terminal === SAMPLE_LOG_HEADER.home_terminal
        ? { ...header, home_terminal: placeLabel(input.current_location.label) }
        : header,
    [header, input.current_location.label],
  )
  const notes = useMemo(
    () => new Map(plan.daily_logs.map((l) => [l.date, dutyPeriodNote(plan.timeline, l.date)])),
    [plan],
  )

  const items: TabItem<TabKey>[] = [
    {
      key: 'logs',
      label: 'Daily Logs',
      icon: <CalendarDays className="size-4" aria-hidden />,
      badge: (
        <span
          className={cn(
            'tabular grid h-5 min-w-5 place-items-center rounded-full px-1.5 font-mono text-[11px] font-semibold',
            tab === 'logs' ? 'bg-hw-650 text-white' : 'bg-ink-200 text-ink-600',
          )}
        >
          {plan.daily_logs.length}
        </span>
      ),
    },
    { key: 'itinerary', label: 'Itinerary', icon: <ListOrdered className="size-4" aria-hidden /> },
    { key: 'directions', label: 'Directions', icon: <Signpost className="size-4" aria-hidden /> },
  ]

  return (
    <Card id="results" tabIndex={-1} role="region" aria-label="Trip results" className="animate-fade-up scroll-mt-20 focus:outline-none">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-150 px-4 py-3 sm:px-6" data-print-hide>
        <Tabs items={items} value={tab} onChange={onTabChange} idPrefix="results" label="Trip results" />
        <div className="flex min-w-0 items-center gap-3">
          <p className="hidden min-w-0 truncate text-xs text-ink-500 xl:block">{tripLabel}</p>
          {shareUrl && <ShareLinkButton url={shareUrl} />}
        </div>
      </div>
      <div
        role="tabpanel"
        id={`results-panel-${tab}`}
        aria-labelledby={`results-tab-${tab}`}
        tabIndex={0}
        className="px-3 py-5 focus-visible:outline-none sm:px-6"
      >
        {tab === 'itinerary' && (
          <ItineraryView
            timeline={plan.timeline}
            dailyLogs={plan.daily_logs}
            homeTzAbbr={input.home_tz_abbr}
            selectedId={selectedId}
            onSelect={onSelectEvent}
          />
        )}
        {tab === 'logs' && (
          <DailyLogsView logs={plan.daily_logs} header={sheetHeader} tripLabel={tripLabel} notes={notes} tzAbbr={input.home_tz_abbr} />
        )}
        {tab === 'directions' && <DirectionsView plan={plan} />}
      </div>
      <PrintLogs logs={plan.daily_logs} header={sheetHeader} tripLabel={tripLabel} notes={notes} tzAbbr={input.home_tz_abbr} />
    </Card>
  )
}
