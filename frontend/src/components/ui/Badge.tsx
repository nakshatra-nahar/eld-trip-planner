import type { HTMLAttributes } from 'react'
import { DUTY_STATUS } from '../../lib/duty'
import { cn } from '../../lib/cn'
import type { DutyStatus } from '../../types/api'

type Tone = 'neutral' | 'ink' | 'accent' | 'warning'

const TONES: Record<Tone, string> = {
  neutral: 'bg-ink-100 text-ink-600 ring-ink-200',
  ink: 'bg-ink-900 text-white ring-ink-900',
  accent: 'bg-hw-50 text-hw-700 ring-hw-200',
  warning: 'bg-duty-on-soft text-[#92400e] ring-duty-on/30',
}

export function Badge({ tone = 'neutral', className, ...rest }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] leading-4 font-semibold ring-1 ring-inset',
        TONES[tone],
        className,
      )}
      {...rest}
    />
  )
}

/** Compact duty-status chip: colored dot + ELD code, full label for assistive tech. */
export function StatusChip({ status, className, long = false }: { status: DutyStatus; className?: string; long?: boolean }) {
  const meta = DUTY_STATUS[status]
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1.5 rounded-md px-2 font-mono text-[11px] font-semibold tracking-wide ring-1 ring-inset',
        meta.chip,
        className,
      )}
      title={meta.label}
    >
      <span className={cn('size-1.5 rounded-full', meta.dot)} aria-hidden />
      {long ? meta.label : <><span aria-hidden>{meta.short}</span><span className="sr-only">{meta.label}</span></>}
    </span>
  )
}
