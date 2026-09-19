import { type ReactNode, useId } from 'react'
import { cn } from '../../lib/cn'

interface TooltipProps {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom'
  /** Horizontal alignment relative to the trigger; use 'end' near the right edge of the screen. */
  align?: 'center' | 'end'
  className?: string
}

/** CSS-only tooltip shown on hover and keyboard focus of the wrapped element. */
export function Tooltip({ content, children, side = 'top', align = 'center', className }: TooltipProps) {
  const id = useId()
  return (
    <span className={cn('group/tt relative inline-flex', className)} aria-describedby={id}>
      {children}
      <span
        id={id}
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-50 w-max max-w-64 rounded-lg bg-ink-900 px-2.5 py-1.5 text-xs leading-snug font-medium text-white opacity-0 shadow-pop transition-opacity duration-150',
          'group-hover/tt:opacity-100 group-focus-within/tt:opacity-100',
          side === 'top' ? 'bottom-full mb-2' : 'top-full mt-2',
          align === 'center' ? 'left-1/2 -translate-x-1/2' : 'right-0',
        )}
      >
        {content}
      </span>
    </span>
  )
}
