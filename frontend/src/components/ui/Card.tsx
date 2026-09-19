import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-[var(--radius-card)] bg-white shadow-card ring-1 ring-ink-900/[0.06]', className)}
      {...rest}
    />
  )
}
