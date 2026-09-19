import { type KeyboardEvent, type ReactNode, useRef } from 'react'
import { cn } from '../../lib/cn'

export interface TabItem<K extends string> {
  key: K
  label: string
  icon?: ReactNode
  badge?: ReactNode
}

interface TabsProps<K extends string> {
  items: TabItem<K>[]
  value: K
  onChange: (key: K) => void
  idPrefix: string
  label: string
  className?: string
}

/** WAI-ARIA tablist with roving focus (arrow keys, Home/End). Panels use `${idPrefix}-panel-${key}`. */
export function Tabs<K extends string>({ items, value, onChange, idPrefix, label, className }: TabsProps<K>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([])

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const index = items.findIndex((t) => t.key === value)
    let next = index
    if (e.key === 'ArrowRight') next = (index + 1) % items.length
    else if (e.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = items.length - 1
    else return
    e.preventDefault()
    onChange(items[next].key)
    refs.current[next]?.focus()
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cn('flex w-full gap-1 overflow-x-auto rounded-xl bg-ink-150/80 p-1 [scrollbar-width:none] sm:w-auto', className)}
    >
      {items.map((item, i) => {
        const selected = item.key === value
        return (
          <button
            key={item.key}
            ref={(el) => {
              refs.current[i] = el
            }}
            role="tab"
            type="button"
            id={`${idPrefix}-tab-${item.key}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${item.key}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.key)}
            className={cn(
              'inline-flex h-10 flex-1 items-center justify-center gap-1.5 rounded-[9px] px-2.5 text-sm font-medium whitespace-nowrap transition-all duration-150 sm:flex-none sm:gap-2 sm:px-4 [&>svg]:hidden sm:[&>svg]:block',
              selected ? 'bg-white text-ink-900 shadow-card' : 'text-ink-500 hover:text-ink-800',
            )}
          >
            {item.icon}
            {item.label}
            {item.badge}
          </button>
        )
      })}
    </div>
  )
}
