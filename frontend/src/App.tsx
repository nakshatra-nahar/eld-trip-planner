import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MapFocus } from './components/map/mapModel'
import { type PreviewPoint, TripMap } from './components/map/TripMap'
import { PlannerForm } from './components/planner/PlannerForm'
import { TripOverview } from './components/planner/TripOverview'
import { DEFAULT_OPTIONS, EMPTY_LOCATION, fromResolved, type PlannerErrors, type PlannerValues } from './components/planner/types'
import { liveServerErrors, mapServerDetails } from './components/planner/validation'
import { ResultsPanel } from './components/results/ResultsPanel'
import { EmptyState } from './components/states/EmptyState'
import { ErrorState } from './components/states/ErrorState'
import { ResultsSkeleton } from './components/states/ResultsSkeleton'
import { TripSummary, TripSummarySkeleton } from './components/summary/TripSummary'
import { TopBar } from './components/TopBar'
import { Card } from './components/ui'
import { EMPTY_LOG_HEADER, SAMPLE_LOG_HEADER, useLogHeader } from './hooks/useLogHeader'
import { api, type ApiClient, ApiRequestError, describeError } from './lib/api'
import { formatMiles, nextFullHour, placeLabel } from './lib/format'
import {
  decodePlanQuery,
  encodePlanQuery,
  readCachedPlan,
  requestFromPlan,
  withPlanQuery,
  writeCachedPlan,
} from './lib/planQuery'
import type { LocationInput, PlanRequest, PlanResponse, TimelineEvent } from './types/api'

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

function valuesFromRequest(request: PlanRequest): PlannerValues {
  const loc = ({ label, query, lat, lon }: LocationInput) =>
    lat !== undefined && lon !== undefined
      ? fromResolved(placeLabel(label ?? query ?? ''), lat, lon)
      : { ...EMPTY_LOCATION, text: query ?? label ?? '' }
  return {
    current: loc(request.current_location),
    pickup: loc(request.pickup_location),
    dropoff: loc(request.dropoff_location),
    cycleUsed: String(request.current_cycle_used_hours),
    startTime: request.start_time,
    options: { ...DEFAULT_OPTIONS, ...request.options },
  }
}

// ---------- URL & history ----------
// A planned trip lives in the URL (lib/planQuery), so it can be shared, reloaded and navigated:
// results entries carry the plan query; form entries (Edit, New trip) drop it. history.state
// records which view an entry shows, so Back from the results returns to the form.

type HistoryEntry = { view: 'form' | 'results'; fresh?: boolean }

function historyEntry(): HistoryEntry | null {
  const state: unknown = window.history.state
  return state && typeof state === 'object' && 'view' in state ? (state as HistoryEntry) : null
}

/** This page's URL with the plan query replaced (null = removed); ?demo= and the hash are kept. */
function pageUrl(planQuery: string | null): string {
  const { pathname, search, hash } = window.location
  return `${pathname}${withPlanQuery(search, planQuery)}${hash}`
}

const planQueryOf = (plan: PlanResponse) => encodePlanQuery(requestFromPlan(plan))

/** A plan URL opened directly (shared link or reload): its request, and the response if cached. */
const BOOT = (() => {
  if (IS_DEMO) return null
  const request = decodePlanQuery(window.location.search)
  return request ? { request, cached: readCachedPlan(encodePlanQuery(request)) } : null
})()

function valuesFromPlan(plan: PlanResponse): PlannerValues {
  const { input } = plan
  const loc = (l: PlanResponse['input']['current_location']) => fromResolved(placeLabel(l.label), l.lat, l.lon)
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
  const [values, setValues] = useState<PlannerValues>(() =>
    BOOT?.cached ? valuesFromPlan(BOOT.cached) : BOOT ? valuesFromRequest(BOOT.request) : initialValues(),
  )
  const [status, setStatus] = useState<Status>(BOOT?.cached ? 'success' : BOOT ? 'loading' : 'idle')
  const [plan, setPlan] = useState<PlanResponse | null>(BOOT?.cached ?? null)
  const [error, setError] = useState<{ title: string; message: string; retryable: boolean } | null>(null)
  const [serverErrors, setServerErrors] = useState<PlannerErrors>({})
  /** The form as it was when the server rejected it: an error clears once its field changes. */
  const [rejectedValues, setRejectedValues] = useState<PlannerValues | null>(null)
  const [editing, setEditing] = useState(!BOOT?.cached)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [focus, setFocus] = useState<MapFocus | null>(null)
  const [lastRequest, setLastRequest] = useState<PlanRequest | null>(BOOT?.request ?? null)
  /** True while the plan on screen is the bundled sample, not a live result. */
  const [isSample, setIsSample] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const { header, setHeader, update: updateHeader } = useLogHeader()

  const inflight = useRef<AbortController | null>(null)
  const mapBoxRef = useRef<HTMLDivElement>(null)
  const overviewHeadingRef = useRef<HTMLHeadingElement>(null)
  /** Set when a user action produced the plan, so focus moves to it once it renders. */
  const focusPlan = useRef(false)
  // Latest plan and form values for the popstate handler and error snapshots.
  const planRef = useRef<PlanResponse | null>(null)
  const valuesRef = useRef(values)
  useEffect(() => {
    planRef.current = plan
    valuesRef.current = values
  }, [plan, values])

  const showPlan = useCallback((next: PlanResponse, { focus = false } = {}) => {
    focusPlan.current = focus
    setPlan(next)
    setValues(valuesFromPlan(next))
    setStatus('success')
    setEditing(false)
    setSelectedId(null)
    const sheets = next.daily_logs.length
    setAnnouncement(`Trip planned: ${formatMiles(next.summary.total_miles)}, ${sheets} log sheet${sheets === 1 ? '' : 's'}.`)
  }, [])

  // The form unmounts when a plan arrives; put keyboard and screen-reader focus on the result.
  useEffect(() => {
    if (!plan || editing || !focusPlan.current) return
    focusPlan.current = false
    overviewHeadingRef.current?.focus()
  }, [plan, editing])

  // ?demo=1 / ?demo=restart: swap in the offline client and show its fixture immediately.
  useEffect(() => {
    if (!IS_DEMO) return
    let cancelled = false
    loadDemo(window.location.search).then(({ client: demoClient, plan: demoPlan }) => {
      if (cancelled) return
      setClient(demoClient)
      showPlan(demoPlan)
      if (!historyEntry()) window.history.replaceState({ view: 'results' } satisfies HistoryEntry, '')
    })
    return () => {
      cancelled = true
    }
  }, [showPlan])

  const clearServerErrors = useCallback(() => {
    setServerErrors({})
    setRejectedValues(null)
  }, [])

  /** The request itself; every state update happens after it settles. */
  const fetchPlan = useCallback(
    async (request: PlanRequest, history: 'push' | 'replace' | 'none') => {
      inflight.current?.abort()
      const controller = new AbortController()
      inflight.current = controller
      try {
        const result = await client.planTrip(request, controller.signal)
        const query = planQueryOf(result)
        writeCachedPlan(query, result)
        const entry: HistoryEntry = { view: 'results' }
        if (history === 'push') window.history.pushState(entry, '', pageUrl(query))
        else if (history === 'replace') window.history.replaceState(entry, '', pageUrl(query))
        setIsSample(false)
        showPlan(result, { focus: history === 'push' })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setStatus('error')
        setAnnouncement('')
        // Errors about a specific field are shown on that field; the card is for everything else.
        const fieldErrors =
          err instanceof ApiRequestError && err.code === 'validation_error'
            ? mapServerDetails(err.details)
            : err instanceof ApiRequestError && err.code === 'geocode_failed'
              ? mapServerDetails(err.details, "We couldn't find this place. Pick a suggestion or add the state.")
              : {}
        if (Object.keys(fieldErrors).length) {
          setError(null)
          setServerErrors(fieldErrors)
          setRejectedValues(valuesRef.current)
          setEditing(true)
          requestAnimationFrame(() => document.querySelector<HTMLElement>('form [aria-invalid="true"]')?.focus())
          return
        }
        // Retrying only helps when the failure was transient (network or upstream), not bad input.
        const retryable = !(err instanceof ApiRequestError) || !INPUT_ERRORS.has(err.code)
        setError({ ...describeError(err), retryable })
      }
    },
    [client, showPlan],
  )

  const runPlan = useCallback(
    (request: PlanRequest, { history = 'push' }: { history?: 'push' | 'replace' | 'none' } = {}) => {
      setLastRequest(request)
      setStatus('loading')
      setError(null)
      clearServerErrors()
      return fetchPlan(request, history)
    },
    [fetchPlan, clearServerErrors],
  )

  const resetToNewTrip = useCallback(() => {
    inflight.current?.abort()
    setValues(initialValues())
    setPlan(null)
    setStatus('idle')
    setError(null)
    setSelectedId(null)
    setEditing(true)
    setIsSample(false)
    setAnnouncement('')
    if (!IS_DEMO) setClient(api)
  }, [])

  /** Shows the form for the current values; a plan still on screen stays behind it. */
  const showForm = useCallback(() => {
    if (inflight.current && !inflight.current.signal.aborted) {
      inflight.current.abort()
      setStatus(planRef.current ? 'success' : 'idle')
    }
    setEditing(true)
  }, [])

  /** Shows the plan for a plan query: the one on screen, the session cache, or a fresh request. */
  const showPlanFor = useCallback(
    (request: PlanRequest, history: 'replace' | 'none') => {
      const query = encodePlanQuery(request)
      const current = planRef.current
      if (current && planQueryOf(current) === query) {
        setEditing(false)
        return
      }
      const cached = readCachedPlan(query)
      setValues(valuesFromRequest(request))
      if (cached) {
        setIsSample(false)
        showPlan(cached)
      } else {
        runPlan(request, { history })
      }
    },
    [runPlan, showPlan],
  )

  // Opening a shared or reloaded plan URL: give Back a form to return to, and plan the trip
  // unless the session cache already restored it (state is initialized from BOOT).
  const booted = useRef(false)
  useEffect(() => {
    if (!BOOT || booted.current) return
    booted.current = true
    if (!historyEntry()) {
      const query = encodePlanQuery(BOOT.request)
      window.history.replaceState({ view: 'form' } satisfies HistoryEntry, '', pageUrl(null))
      window.history.pushState({ view: 'results' } satisfies HistoryEntry, '', pageUrl(query))
    }
    // fetchPlan only updates state once the request settles (the loading state came from BOOT).
    // oxlint-disable-next-line react/set-state-in-effect
    if (!BOOT.cached) void fetchPlan(BOOT.request, 'replace')
  }, [fetchPlan])

  // Back/Forward between the form and results entries.
  useEffect(() => {
    const onPop = () => {
      const entry = historyEntry()
      const request = decodePlanQuery(window.location.search)
      if (entry?.view === 'form' || (!request && entry?.view !== 'results')) {
        if (entry?.fresh) resetToNewTrip()
        else showForm()
      } else if (request) {
        showPlanFor(request, 'none')
      } else if (planRef.current) {
        setEditing(false)
      } else {
        showForm()
      }
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [resetToNewTrip, showForm, showPlanFor])

  const shareUrl = useMemo(() => {
    if (!plan || isSample) return undefined
    const { origin, pathname, search } = window.location
    return `${origin}${pathname}${withPlanQuery(IS_DEMO ? search : '', planQueryOf(plan))}`
  }, [plan, isSample])

  const liveErrors = useMemo(() => liveServerErrors(serverErrors, rejectedValues, values), [serverErrors, rejectedValues, values])

  // Only shows the recorded fixture. The live client stays in place, so the next
  // "Plan trip" really plans the trip that was entered.
  const loadSample = useCallback(async () => {
    const { plan: sample } = await loadDemo('?demo=1')
    window.history.pushState({ view: 'results' } satisfies HistoryEntry, '', pageUrl(null))
    setIsSample(true)
    showPlan(sample, { focus: true })
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
    return entries.flatMap(([role, s]) => (s ? [{ role, lngLat: [s.lon, s.lat], label: placeLabel(s.short_label) }] : []))
  }, [cur.selected, pu.selected, dr.selected])

  const loading = status === 'loading'
  const formVisible = editing || !plan

  return (
    <div className="min-h-dvh">
      <TopBar demo={IS_DEMO || isSample} />
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>

      <main className="mx-auto grid max-w-[1600px] grid-cols-[minmax(0,1fr)] gap-5 px-4 py-5 sm:px-6 lg:py-6">
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[440px_minmax(0,1fr)]">
          {/* Below lg this column dissolves (display: contents) so the map can sit right after
              the trip card and before the long summary. */}
          <div className="contents min-w-0 lg:grid lg:grid-cols-[minmax(0,1fr)] lg:gap-5" data-print-hide>
            <Card>
              {formVisible ? (
                <PlannerForm
                  values={values}
                  onValuesChange={setValues}
                  onSubmit={runPlan}
                  loading={loading}
                  client={client}
                  header={header}
                  onHeaderChange={updateHeader}
                  onHeaderClear={() => setHeader(EMPTY_LOG_HEADER)}
                  onHeaderSample={() => setHeader(SAMPLE_LOG_HEADER)}
                  serverErrors={liveErrors}
                  onSubmitStart={clearServerErrors}
                />
              ) : (
                <TripOverview
                  plan={plan}
                  headingRef={overviewHeadingRef}
                  onEdit={() => {
                    window.history.pushState({ view: 'form' } satisfies HistoryEntry, '', pageUrl(null))
                    setEditing(true)
                  }}
                  onNew={() => {
                    window.history.pushState({ view: 'form', fresh: true } satisfies HistoryEntry, '', pageUrl(null))
                    resetToNewTrip()
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
            <div className="order-1 min-w-0 lg:order-none">
              {loading ? <TripSummarySkeleton /> : plan && <TripSummary key={plan.summary.end_time} plan={plan} />}
            </div>
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
          <ResultsPanel
            plan={plan}
            header={header}
            selectedId={selectedId}
            onSelectEvent={selectEvent}
            shareUrl={shareUrl}
          />
        ) : (
          <div data-print-hide>
            <EmptyState onLoadSample={loadSample} />
          </div>
        )}

        <footer data-print-hide className="flex flex-wrap justify-between gap-2 pb-2 text-xs text-ink-500">
          <p>For trip planning only. Always verify against your ELD and carrier policy.</p>
          <p>
            Maps © OpenFreeMap, © OpenMapTiles, data © OpenStreetMap contributors · Truck routing by Valhalla (FOSSGIS), OSRM fallback · Search by Photon ·
            Places © GeoNames (CC BY 4.0)
          </p>
        </footer>
      </main>
    </div>
  )
}
