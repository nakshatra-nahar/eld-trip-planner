import { type CSSProperties, useId } from 'react'
import { cn } from '../../lib/cn'
import { formatHours } from '../../lib/format'

interface CycleInputProps {
  value: string
  onChange: (value: string) => void
  error?: string
}

const LIMIT = 70

/** "Current Cycle Used" as a number field bound to a 0-70 h slider, with hours-left feedback. */
export function CycleInput({ value, onChange, error }: CycleInputProps) {
  const id = useId()
  const parsed = Number(value)
  const valid = value.trim() !== '' && !Number.isNaN(parsed)
  const used = valid ? Math.min(LIMIT, Math.max(0, parsed)) : 0
  const left = LIMIT - used
  const tone = left <= 0 ? 'danger' : left < 11 ? 'warn' : 'ok'
  const color = tone === 'danger' ? 'var(--color-danger-600)' : tone === 'warn' ? 'var(--color-duty-on)' : 'var(--color-ink-900)'

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-[13px] font-medium text-ink-700">
          Current cycle used
        </label>
        <span className="text-xs text-ink-500">70 h / 8 days</span>
      </div>
      <div className="flex items-center gap-4">
        <div className="relative w-24 shrink-0">
          <input
            id={id}
            type="number"
            inputMode="decimal"
            min={0}
            max={LIMIT}
            step={0.25}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={`${id}-help`}
            className="tabular h-11 w-full rounded-[10px] bg-white pr-8 pl-3 font-mono text-[15px] font-semibold text-ink-900 ring-1 ring-ink-200 ring-inset hover:ring-ink-300 focus:ring-2 focus:ring-ink-900 focus:outline-none aria-[invalid=true]:ring-danger-600"
          />
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-ink-400">h</span>
        </div>
        <input
          type="range"
          min={0}
          max={LIMIT}
          step={0.5}
          value={used}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Current cycle used, hours"
          aria-valuetext={`${formatHours(used)} hours used`}
          className="range-track h-11 w-full bg-clip-content py-[19px]"
          style={{ '--fill': `${(used / LIMIT) * 100}%`, '--range-color': color } as CSSProperties}
        />
      </div>
      <p
        id={`${id}-help`}
        className={cn(
          'mt-1.5 text-xs',
          error ? 'font-medium text-danger-700' : tone === 'ok' ? 'text-ink-500' : tone === 'warn' ? 'font-medium text-[#b45309]' : 'font-medium text-danger-700',
        )}
      >
        {error ??
          (tone === 'danger'
            ? 'No hours left: the plan will start with a 34-hour restart.'
            : `${formatHours(left)} h available in the cycle${tone === 'warn' ? ', a 34-hour restart is likely.' : '.'}`)}
      </p>
    </div>
  )
}
