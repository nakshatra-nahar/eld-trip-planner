import { ChevronDown } from 'lucide-react'
import { type ReactNode, useId, useState } from 'react'
import { cn } from '../../lib/cn'

interface DisclosureProps {
  title: string
  icon?: ReactNode
  summary?: ReactNode
  defaultOpen?: boolean
  /** Opens the section when it becomes true, e.g. to reveal a field with an error. */
  forceOpen?: boolean
  children: ReactNode
}

/** Collapsible section with an accessible header button. Content height animates via CSS grid rows. */
export function Disclosure({ title, icon, summary, defaultOpen = false, forceOpen = false, children }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen || forceOpen)
  // Open when forceOpen turns on (adjusting state during render, not in an effect).
  const [wasForced, setWasForced] = useState(forceOpen)
  if (forceOpen !== wasForced) {
    setWasForced(forceOpen)
    if (forceOpen) setOpen(true)
  }
  const id = useId()
  return (
    <div className="border-t border-ink-150">
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((o) => !o)}
          className="group flex min-h-12 w-full items-center gap-2.5 py-2 text-left"
        >
          <span className="text-ink-400 group-hover:text-ink-700">{icon}</span>
          <span className="text-sm font-semibold text-ink-800">{title}</span>
          {summary && !open && <span className="ml-auto min-w-0 truncate pl-2 text-xs text-ink-500">{summary}</span>}
          <ChevronDown
            aria-hidden
            className={cn(
              'size-4 shrink-0 text-ink-400 transition-transform duration-200',
              open && 'rotate-180',
              (!summary || open) && 'ml-auto',
            )}
          />
        </button>
      </h3>
      <div
        id={id}
        role="region"
        aria-label={title}
        hidden={!open}
        className="grid pb-4 animate-fade-up"
      >
        {children}
      </div>
    </div>
  )
}
