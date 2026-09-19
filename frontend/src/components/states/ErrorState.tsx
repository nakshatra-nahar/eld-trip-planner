import { CircleAlert, RefreshCw } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { scrollBehavior } from '../../lib/motion'
import { Button } from '../ui'

interface ErrorStateProps {
  title: string
  message: string
  onRetry?: () => void
}

export function ErrorState({ title, message, onRetry }: ErrorStateProps) {
  const ref = useRef<HTMLDivElement>(null)
  // The card renders below a tall form; bring it into view so a failed plan never looks like a no-op.
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'nearest' })
  }, [title, message])

  return (
    <div
      ref={ref}
      role="alert"
      className="flex animate-fade-up gap-3 rounded-[var(--radius-card)] bg-danger-50 p-4 ring-1 ring-danger-600/20 sm:p-5"
    >
      <CircleAlert className="mt-0.5 size-5 shrink-0 text-danger-600" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-danger-700">{title}</p>
        <p className="mt-0.5 text-sm leading-relaxed text-ink-700">{message}</p>
        {onRetry && (
          <Button size="sm" className="mt-3" onClick={onRetry} icon={<RefreshCw className="size-3.5" aria-hidden />}>
            Try again
          </Button>
        )}
      </div>
    </div>
  )
}
