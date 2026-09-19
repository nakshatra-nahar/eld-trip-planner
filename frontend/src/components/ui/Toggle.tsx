import { useId } from 'react'
import { cn } from '../../lib/cn'

interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  description?: string
}

/** Accessible switch (button role="switch") with label and optional description. */
export function Toggle({ checked, onChange, label, description }: ToggleProps) {
  const id = useId()
  return (
    <div className="flex min-h-11 items-center justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-ink-800">
          {label}
        </label>
        {description && (
          <p id={`${id}-desc`} className="text-xs text-ink-500">
            {description}
          </p>
        )}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-describedby={description ? `${id}-desc` : undefined}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-200',
          'before:absolute before:-inset-2.5 before:content-[""]',
          checked ? 'bg-ink-900' : 'bg-ink-300',
        )}
      >
        <span
          className={cn(
            'inline-block size-5 rounded-full bg-white shadow-sm transition-transform duration-200',
            checked ? 'translate-x-[22px]' : 'translate-x-0.5',
          )}
        />
      </button>
    </div>
  )
}
