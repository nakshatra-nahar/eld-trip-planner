import { ArrowUpDown, CalendarClock, CircleAlert, IdCard, Route, Settings2, Sparkles } from 'lucide-react'
import { type FormEvent, type ReactNode, useState } from 'react'
import type { ApiClient } from '../../lib/api'
import { cn } from '../../lib/cn'
import { ROLE_ICON } from '../../lib/duty'
import type { LogHeaderDetails, PlanRequest } from '../../types/api'
import { Button, Disclosure, Field, SegmentedControl, Toggle } from '../ui'
import { CycleInput } from './CycleInput'
import { EXAMPLE_TRIPS } from './examples'
import { LocationCombobox } from './LocationCombobox'
import { LogHeaderFields } from './LogHeaderFields'
import { type LocationValue, type PlannerErrors, type PlannerValues, toLocationInput } from './types'
import { UseMyLocationButton } from './UseMyLocationButton'
import { FUEL_MINUTES, validatePlanner } from './validation'

interface PlannerFormProps {
  values: PlannerValues
  onValuesChange: (update: (prev: PlannerValues) => PlannerValues) => void
  onSubmit: (request: PlanRequest) => void
  loading: boolean
  client: ApiClient
  header: LogHeaderDetails
  onHeaderChange: <K extends keyof LogHeaderDetails>(key: K, value: LogHeaderDetails[K]) => void
  onHeaderClear: () => void
  onHeaderSample: () => void
  serverErrors?: PlannerErrors
  /** Called first on every submit, before client validation, so stale server errors clear. */
  onSubmitStart?: () => void
}

type LocationKey = 'current' | 'pickup' | 'dropoff'

export function PlannerForm({
  values,
  onValuesChange,
  onSubmit,
  loading,
  client,
  header,
  onHeaderChange,
  onHeaderClear,
  onHeaderSample,
  serverErrors,
  onSubmitStart,
}: PlannerFormProps) {
  const [submitted, setSubmitted] = useState(false)
  const [geoError, setGeoError] = useState<string | null>(null)
  // Validate live once the user has tried to submit, so errors clear as they are fixed.
  const shown: PlannerErrors = { ...serverErrors, ...(submitted ? validatePlanner(values) : {}) }

  function patch(update: Partial<PlannerValues>) {
    onValuesChange((prev) => ({ ...prev, ...update }))
  }

  const setLocation = (key: LocationKey) => (value: LocationValue) => patch({ [key]: value })

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    onSubmitStart?.()
    const found = validatePlanner(values)
    setSubmitted(true)
    if (Object.keys(found).length) {
      // Focus the first invalid field once the error state has rendered.
      requestAnimationFrame(() => document.querySelector<HTMLElement>('form [aria-invalid="true"]')?.focus())
      return
    }
    onSubmit({
      current_location: toLocationInput(values.current),
      pickup_location: toLocationInput(values.pickup),
      dropoff_location: toLocationInput(values.dropoff),
      current_cycle_used_hours: Number(values.cycleUsed),
      start_time: values.startTime,
      options: values.options,
    })
  }

  const { options } = values

  return (
    <form noValidate onSubmit={handleSubmit} aria-label="Trip planner" className="flex flex-col">
      <div className="px-5 pt-5 sm:px-6">
        <p className="text-[11px] font-semibold tracking-[0.14em] text-hw-700 uppercase">New trip</p>
        <h1 className="mt-0.5 font-display text-[22px] leading-tight font-extrabold tracking-tight text-ink-900">
          Plan an HOS-compliant run
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-1.5" role="group" aria-label="Example trips">
          <span className="mr-0.5 inline-flex items-center gap-1 text-xs font-medium text-ink-500">
            <Sparkles className="size-3.5 text-hw-500" aria-hidden /> Try
          </span>
          {EXAMPLE_TRIPS.map((ex) => (
            <button
              key={ex.id}
              type="button"
              title={ex.detail}
              onClick={() => {
                setGeoError(null)
                patch(ex.values)
              }}
              className="relative h-7 rounded-full bg-ink-100 px-2.5 text-xs font-medium text-ink-700 ring-1 ring-ink-200 ring-inset transition-colors before:absolute before:-inset-y-2 before:inset-x-0 hover:bg-hw-50 hover:text-hw-700 hover:ring-hw-200"
            >
              {ex.title}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5 px-5 sm:px-6">
        <RailRow icon={<RailIcon role="current" />}>
          <LocationCombobox
            label="Current location"
            placeholder="Where is the truck now?"
            value={values.current}
            onChange={(v) => {
              setGeoError(null)
              setLocation('current')(v)
            }}
            client={client}
            error={shown.current ?? geoError ?? undefined}
            action={
              <UseMyLocationButton
                client={client}
                onLocated={(v) => {
                  setGeoError(null)
                  setLocation('current')(v)
                }}
                onError={setGeoError}
              />
            }
          />
        </RailRow>
        <RailRow icon={<RailIcon role="pickup" />}>
          <LocationCombobox
            label="Pickup"
            placeholder="Shipper city or address"
            value={values.pickup}
            onChange={setLocation('pickup')}
            client={client}
            error={shown.pickup}
          />
          <button
            type="button"
            onClick={() => patch({ pickup: values.dropoff, dropoff: values.pickup })}
            aria-label="Swap pickup and dropoff"
            title="Swap pickup and dropoff"
            className="absolute -top-1 right-0 inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs font-medium text-ink-500 hover:bg-ink-100 hover:text-ink-900"
          >
            <ArrowUpDown className="size-3.5" aria-hidden /> Swap
          </button>
        </RailRow>
        <RailRow icon={<RailIcon role="dropoff" />} last>
          <LocationCombobox
            label="Dropoff"
            placeholder="Receiver city or address"
            value={values.dropoff}
            onChange={setLocation('dropoff')}
            client={client}
            error={shown.dropoff}
          />
        </RailRow>
      </div>

      <div className="mt-5 grid gap-4 border-t border-ink-150 px-5 pt-5 sm:px-6">
        <CycleInput value={values.cycleUsed} onChange={(v) => patch({ cycleUsed: v })} error={shown.cycleUsed} />
        <Field
          label="Trip start"
          type="datetime-local"
          value={values.startTime}
          onChange={(e) => patch({ startTime: e.target.value })}
          error={shown.startTime}
          hint="Home-terminal time. Defaults to the next full hour."
          leading={<CalendarClock className="size-4" aria-hidden />}
          className="tabular"
        />
      </div>

      <div className="mt-5 px-5 sm:px-6">
        <Disclosure
          title="Advanced"
          icon={<Settings2 className="size-4" aria-hidden />}
          summary={`${options.include_inspections ? 'Inspections' : 'No insp.'} · ${options.rest_status} rest · ${options.fuel_stop_minutes}m fuel`}
          forceOpen={Boolean(shown.fuel)}
        >
          <div className="grid gap-3">
            <Toggle
              label="Pre- & post-trip inspections"
              description="30 min on duty at each duty-period start, 15 min before each rest."
              checked={options.include_inspections}
              onChange={(v) => patch({ options: { ...options, include_inspections: v } })}
            />
            <SegmentedControl
              label="10-hour rest logged as"
              value={options.rest_status}
              options={[
                { value: 'SB', label: 'Sleeper berth' },
                { value: 'OFF', label: 'Off duty' },
              ]}
              onChange={(v) => patch({ options: { ...options, rest_status: v } })}
            />
            <Field
              label="Fuel stop duration"
              type="number"
              inputMode="numeric"
              min={FUEL_MINUTES.min}
              max={FUEL_MINUTES.max}
              step={5}
              value={Number.isFinite(options.fuel_stop_minutes) ? options.fuel_stop_minutes : ''}
              onChange={(e) => patch({ options: { ...options, fuel_stop_minutes: Math.round(e.target.valueAsNumber) } })}
              error={shown.fuel}
              hint="On duty (not driving). A stop is planned at least every 1,000 miles."
              trailing={<span className="pr-3 text-sm text-ink-400">min</span>}
              className="tabular"
            />
          </div>
        </Disclosure>
        <Disclosure
          title="Log sheet details"
          icon={<IdCard className="size-4" aria-hidden />}
          summary={header.driver_name || 'Not set'}
        >
          <LogHeaderFields value={header} onChange={onHeaderChange} />
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-xs text-ink-500">
              Starts with the FMCSA guide&rsquo;s sample driver. Edit to match yours; saved in this browser only.
            </p>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={onHeaderSample}>
                Reset to sample
              </Button>
              <Button size="sm" variant="ghost" onClick={onHeaderClear}>
                Clear
              </Button>
            </div>
          </div>
        </Disclosure>
      </div>

      <div className="sticky bottom-0 z-10 mt-1 rounded-b-[var(--radius-card)] border-t border-ink-150 bg-white/95 px-5 py-4 backdrop-blur sm:px-6">
        {Object.keys(shown).length > 0 && (
          <p role="alert" className="mb-3 flex items-center gap-2 text-xs font-medium text-danger-700">
            <CircleAlert className="size-4 shrink-0" aria-hidden /> Fix the highlighted fields to plan this trip.
          </p>
        )}
        <Button
          type="submit"
          variant="accent"
          size="lg"
          loading={loading}
          icon={<Route className="size-[18px]" aria-hidden />}
          className="w-full"
        >
          {loading ? 'Planning route & HOS schedule…' : 'Plan trip'}
        </Button>
      </div>
    </form>
  )
}

/** One stop on the vertical "route rail": icon column with a lane-dash connector, and the field. */
function RailRow({ icon, children, last = false }: { icon: ReactNode; children: ReactNode; last?: boolean }) {
  return (
    <div className={cn('relative grid grid-cols-[28px_minmax(0,1fr)] gap-3', !last && 'pb-3.5')}>
      <div className="relative pt-[32px]">
        {icon}
        {!last && (
          <span
            aria-hidden
            className="absolute top-[64px] -bottom-[30px] left-1/2 w-[2px] -translate-x-1/2 bg-[repeating-linear-gradient(to_bottom,var(--color-hw-400)_0_6px,transparent_6px_11px)]"
          />
        )}
      </div>
      <div className="relative min-w-0">{children}</div>
    </div>
  )
}

function RailIcon({ role }: { role: keyof typeof ROLE_ICON }) {
  const Icon = ROLE_ICON[role]
  return (
    <span
      className={cn(
        'grid size-7 place-items-center rounded-full',
        role === 'current' && 'bg-white text-ink-900 ring-2 ring-ink-900',
        role === 'pickup' && 'bg-hw-500 text-white',
        role === 'dropoff' && 'bg-ink-900 text-white',
      )}
    >
      <Icon className="size-3.5" aria-hidden strokeWidth={2.4} />
    </span>
  )
}
