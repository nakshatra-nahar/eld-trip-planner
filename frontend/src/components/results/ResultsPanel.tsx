import { CalendarDays, ListOrdered, Signpost } from 'lucide-react'
import { useState } from 'react'
import { cn } from '../../lib/cn'
import { placeLabel } from '../../lib/format'
import type { LogHeaderDetails, PlanResponse, TimelineEvent } from '../../types/api'
import { DailyLogsView } from '../logsheet'
import { Card, type TabItem, Tabs } from '../ui'
import { DirectionsView } from './DirectionsView'
import { ItineraryView } from './ItineraryView'

type TabKey = 'itinerary' | 'logs' | 'directions'

interface ResultsPanelProps {
  plan: PlanResponse
  header: LogHeaderDetails
  selectedId: string | null
  onSelectEvent: (event: TimelineEvent) => void
}

export function ResultsPanel({ plan, header, selectedId, onSelectEvent }: ResultsPanelProps) {
  const [tab, setTab] = useState<TabKey>('itinerary')
  const { input } = plan
  const tripLabel = [input.current_location, input.pickup_location, input.dropoff_location].map((l) => placeLabel(l.label)).join(' → ')

  const items: TabItem<TabKey>[] = [
    { key: 'itinerary', label: 'Itinerary', icon: <ListOrdered className="size-4" aria-hidden /> },
    {
      key: 'logs',
      label: 'Daily Logs',
      icon: <CalendarDays className="size-4" aria-hidden />,
      badge: (
        <span
          className={cn(
            'tabular grid h-5 min-w-5 place-items-center rounded-full px-1.5 font-mono text-[11px] font-semibold',
            tab === 'logs' ? 'bg-hw-500 text-white' : 'bg-ink-200 text-ink-600',
          )}
        >
          {plan.daily_logs.length}
        </span>
      ),
    },
    { key: 'directions', label: 'Directions', icon: <Signpost className="size-4" aria-hidden /> },
  ]

  return (
    <Card className="animate-fade-up">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-150 px-4 py-3 sm:px-6" data-print-hide>
        <Tabs items={items} value={tab} onChange={setTab} idPrefix="results" label="Trip results" />
        <p className="hidden truncate text-xs text-ink-500 lg:block">{tripLabel}</p>
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
            selectedId={selectedId}
            onSelect={onSelectEvent}
          />
        )}
        {tab === 'logs' && <DailyLogsView logs={plan.daily_logs} header={header} tripLabel={tripLabel} />}
        {tab === 'directions' && <DirectionsView plan={plan} />}
      </div>
    </Card>
  )
}
