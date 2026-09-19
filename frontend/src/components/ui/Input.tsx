import { forwardRef, type InputHTMLAttributes, type ReactNode, useId } from 'react'
import { cn } from '../../lib/cn'

export const inputClass =
  'h-11 w-full rounded-[10px] bg-white px-3 text-sm text-ink-900 ring-1 ring-inset ring-ink-200 transition-shadow placeholder:text-ink-400 hover:ring-ink-300 focus:ring-2 focus:ring-ink-900 focus:outline-none aria-[invalid=true]:ring-danger-600'

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  hint?: ReactNode
  error?: string
  leading?: ReactNode
  trailing?: ReactNode
}

/** Labeled text input with optional leading icon, trailing adornment, hint and error. */
export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, hint, error, leading, trailing, className, id: idProp, ...rest },
  ref,
) {
  const autoId = useId()
  const id = idProp ?? autoId
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium text-ink-700">
        {label}
      </label>
      <div className="relative">
        {leading && (
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-ink-400">{leading}</span>
        )}
        <input
          ref={ref}
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(inputClass, leading ? 'pl-9' : undefined, trailing ? 'pr-12' : undefined)}
          {...rest}
        />
        {trailing && <span className="absolute inset-y-0 right-1 flex items-center">{trailing}</span>}
      </div>
      {error ? (
        <p id={`${id}-err`} className="mt-1.5 text-xs font-medium text-danger-700">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-ink-500">
          {hint}
        </p>
      ) : null}
    </div>
  )
})
