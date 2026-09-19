import { useId } from 'react'
import { cn } from '../../lib/cn'

interface SegmentedControlProps<V extends string> {
  label: string
  value: V
  options: Array<{ value: V; label: string }>
  onChange: (value: V) => void
}

/** Radio group rendered as a segmented control. */
export function SegmentedControl<V extends string>({ label, value, options, onChange }: SegmentedControlProps<V>) {
  const name = useId()
  return (
    <fieldset>
      <legend className="mb-1.5 text-[13px] font-medium text-ink-700">{label}</legend>
      <div className="grid auto-cols-fr grid-flow-col gap-1 rounded-[10px] bg-ink-150 p-1">
        {options.map((opt) => (
          <label
            key={opt.value}
            className={cn(
              'flex h-9 cursor-pointer items-center justify-center rounded-lg text-[13px] font-medium transition-all has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-hw-500',
              value === opt.value ? 'bg-white text-ink-900 shadow-card' : 'text-ink-500 hover:text-ink-800',
            )}
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
            />
            {opt.label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}
