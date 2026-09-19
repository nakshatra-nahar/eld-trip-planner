import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-[var(--radius-card)] bg-white shadow-card ring-1 ring-ink-900/[0.06]', className)}
      {...rest}
    />
  )
}

interface SectionHeadingProps {
  eyebrow?: string
  title: string
  aside?: ReactNode
  className?: string
}

/** Small uppercase eyebrow + display title, used at the top of cards and sections. */
export function SectionHeading({ eyebrow, title, aside, className }: SectionHeadingProps) {
  return (
    <div className={cn('flex items-end justify-between gap-3', className)}>
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-[11px] font-semibold tracking-[0.14em] text-ink-500 uppercase">{eyebrow}</p>
        )}
        <h2 className="font-display text-[17px] leading-tight font-bold tracking-tight text-ink-900">{title}</h2>
      </div>
      {aside}
    </div>
  )
}
