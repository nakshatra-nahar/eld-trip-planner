import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MapFocus } from './components/map/mapModel'
import { type PreviewPoint, TripMap } from './components/map/TripMap'
import { PlannerForm } from './components/planner/PlannerForm'
import { TripOverview } from './components/planner/TripOverview'
import { DEFAULT_OPTIONS, EMPTY_LOCATION, fromResolved, type PlannerErrors, type PlannerValues } from './components/planner/types'
import { mapServerDetails } from './components/planner/validation'
import { ResultsPanel } from './components/results/ResultsPanel'
import { EmptyState } from './components/states/EmptyState'
import { ErrorState } from './components/states/ErrorState'
import { ResultsSkeleton } from './components/states/ResultsSkeleton'
import { TripSummary, TripSummarySkeleton } from './components/summary/TripSummary'
import { TopBar } from './components/TopBar'
import { Card } from './components/ui'
import { EMPTY_LOG_HEADER, useLogHeader } from './hooks/useLogHeader'
import { api, type ApiClient, ApiRequestError, describeError } from './lib/api'
import { nextFullHour } from './lib/format'
import type { PlanRequest, PlanResponse, TimelineEvent } from './types/api'

type Status = 'idle' | 'loading' | 'success' | 'error'

/** Error codes caused by the request itself, where retrying the same request cannot help. */
const INPUT_ERRORS = new Set(['validation_error', 'geocode_failed', 'route_not_found'])

const IS_DEMO = (() => {
  const demo = new URLSearchParams(window.location.search).get('demo')
  return Boolean(demo) && demo !== '0' && demo !== 'false'
})()

function initialValues(): PlannerValues {
  return {
    current: EMPTY_LOCATION,
    pickup: EMPTY_LOCATION,
    dropoff: EMPTY_LOCATION,
    cycleUsed: '0',
    startTime: nextFullHour(),
    options: DEFAULT_OPTIONS,
  }
}

function valuesFromPlan(plan: PlanResponse): PlannerValues {
  const { input } = plan
  const loc = (l: PlanResponse['input']['current_location']) => fromResolved(l.label, l.lat, l.lon)
  return {
    current: loc(input.current_location),
    pickup: loc(input.pickup_location),
    dropoff: loc(input.dropoff_location),
    cycleUsed: String(input.current_cycle_used_hours),
    startTime: input.start_time,
    options: input.options,
  }
}

/** Loads the mock fixtures lazily so they never ship in the main bundle. */
async function loadDemo(search: string) {
  const mod = await import('./mocks/demoClient')
  const plan = await mod.loadDemoPlan(search)
  return { client: mod.createDemoClient(plan), plan }
}

export default function App() {
  const [client, setClient] = useState<ApiClient>(api)
  const [values, setValues] = useState<PlannerValues>(initialValues)
  const [status, setStatus] = useState<Status>('idle')
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [error, setError] = useState<{ title: string; message: string; retryable: boolean } | null>(null)
  const [serverErrors, setServerErrors] = useState<PlannerErrors>({})
  const [editing, setEditing] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [focus, setFocus] = useState<MapFocus | null>(null)
  const [lastRequest, setLastRequest] = useState<PlanRequest | null>(null)
  const { header, setHeader, update: updateHeader } = useLogHeader()

  const inflight = useRef<AbortController | null>(null)
  const mapBoxRef = useRef<HTMLDivElement>(null)

  const showPlan = useCallback((next: PlanResponse) => {
    setPlan(next)
    setValues(valuesFromPlan(next))
    setStatus('success')
    setEditing(false)
    setSelectedId(null)
  }, [])

  // ?demo=1 / ?demo=restart: swap in the offline client and show its fixture immediately.
  useEffect(() => {
    if (!IS_DEMO) return
    let cancelled = false
    loadDemo(window.location.search).then(({ client: demoClient, plan: demoPlan }) => {
      if (cancelled) return
      setClient(demoClient)
      showPlan(demoPlan)
    })
    return () => {
      cancelled = true
    }
  }, [showPlan])

  const runPlan = useCallback(
    async (request: PlanRequest) => {
      inflight.current?.abort()
      const controller = new AbortController()
      inflight.current = controller
      setLastRequest(request)
      setStatus('loading')
      setError(null)
      setServerErrors({})
      try {
        const result = await client.planTrip(request, controller.signal)
        showPlan(result)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setStatus('error')
        // Retrying only helps when the failure was transient (network or upstream), not bad input.
        const retryable = !(err instanceof ApiRequestError) || !INPUT_ERRORS.has(err.code)
        setError({ ...describeError(err), retryable })
        if (err instanceof ApiRequestError && err.code === 'validation_error') {
          setServerErrors(mapServerDetails(err.details))
          setEditing(true)
        }
      }
    },
    [client, showPlan],
  )

  const loadSample = useCallback(async () => {
    const demo = await loadDemo('?demo=1')
    setClient(demo.client)
    showPlan(demo.plan)
  }, [showPlan])

  const selectEvent = useCallback((event: TimelineEvent) => {
    setSelectedId(event.id)
    const a = event.start_location
    const b = event.end_location
    setFocus((prev) => ({
      nonce: (prev?.nonce ?? 0) + 1,
      stopId: event.kind === 'drive' ? undefined : event.id,
      ...(event.kind === 'drive'
        ? {
            bounds: [
              [Math.min(a.lon, b.lon), Math.min(a.lat, b.lat)],
              [Math.max(a.lon, b.lon), Math.max(a.lat, b.lat)],
            ],
          }
        : { lngLat: [a.lon, a.lat] }),
    }))
    // On stacked (mobile) layouts, bring the map into view.
    const box = mapBoxRef.current?.getBoundingClientRect()
    if (box && (box.bottom < 60 || box.top > window.innerHeight)) {
      mapBoxRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [])

  // Pins for picked locations before planning; keyed on the selections only, not every keystroke.
  const { current: cur, pickup: pu, dropoff: dr } = values
  const preview = useMemo<PreviewPoint[]>(() => {
    const entries = [
      ['current', cur.selected],
      ['pickup', pu.selected],
      ['dropoff', dr.selected],
    ] as const
    return entries.flatMap(([role, s]) => (s ? [{ role, lngLat: [s.lon, s.lat], label: s.short_label }] : []))
  }, [cur.selected, pu.selected, dr.selected])

  const loading = status === 'loading'
  const showForm = editing || !plan

  return (
    <div className="min-h-dvh">
      <TopBar demo={client !== api} />

      <main className="mx-auto grid max-w-[1600px] grid-cols-[minmax(0,1fr)] gap-5 px-4 py-5 sm:px-6 lg:py-6">
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[440px_minmax(0,1fr)]">
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5" data-print-hide>
            <Card>
              {showForm ? (
                <PlannerForm
                  values={values}
                  onValuesChange={setValues}
                  onSubmit={runPlan}
                  loading={loading}
                  client={client}
                  header={header}
                  onHeaderChange={updateHeader}
                  onHeaderClear={() => setHeader(EMPTY_LOG_HEADER)}
                  serverErrors={serverErrors}
                />
              ) : (
                <TripOverview
                  plan={plan}
                  onEdit={() => setEditing(true)}
                  onNew={() => {
                    setValues(initialValues())
                    setPlan(null)
                    setStatus('idle')
                    setSelectedId(null)
                    setEditing(true)
                  }}
                />
              )}
            </Card>

            {status === 'error' && error && (
              <ErrorState
                title={error.title}
                message={error.message}
                onRetry={error.retryable && lastRequest ? () => runPlan(lastRequest) : undefined}
              />
            )}
            {loading ? <TripSummarySkeleton /> : plan && <TripSummary key={plan.summary.end_time} plan={plan} />}
          </div>

          <div
            ref={mapBoxRef}
            data-print-hide
            className="h-[340px] overflow-hidden rounded-[var(--radius-card)] shadow-card ring-1 ring-ink-900/[0.08] sm:h-[460px] lg:sticky lg:top-[80px] lg:h-[calc(100dvh-104px)] lg:max-h-[900px] lg:min-h-[560px]"
          >
            <TripMap
              plan={plan}
              preview={preview}
              focus={focus}
              selectedStopId={selectedId}
              onSelectStop={setSelectedId}
              loading={loading}
            />
          </div>
        </div>

        {loading ? (
          <ResultsSkeleton />
        ) : plan ? (
          <ResultsPanel plan={plan} header={header} selectedId={selectedId} onSelectEvent={selectEvent} />
        ) : (
          <div data-print-hide>
            <EmptyState onLoadSample={loadSample} />
          </div>
        )}

        <footer data-print-hide className="flex flex-wrap justify-between gap-2 pb-2 text-xs text-ink-400">
          <p>For trip planning only. Always verify against your ELD and carrier policy.</p>
          <p>
            Maps © OpenFreeMap, © OpenMapTiles, data © OpenStreetMap contributors · Routing by OSRM · Search by Photon
          </p>
        </footer>
      </main>
    </div>
  )
}
