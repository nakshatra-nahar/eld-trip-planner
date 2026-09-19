import { LoaderCircle, MapPin, SearchX, WifiOff, X } from 'lucide-react'
import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import type { ApiClient } from '../../lib/api'
import { cn } from '../../lib/cn'
import type { GeocodeResult } from '../../types/api'
import { inputClass } from '../ui'
import type { LocationValue } from './types'

interface LocationComboboxProps {
  label: string
  placeholder: string
  value: LocationValue
  onChange: (value: LocationValue) => void
  client: ApiClient
  error?: string
  /** Extra control rendered inside the input on the right, e.g. "Use my location". */
  action?: ReactNode
}

type SearchState = 'idle' | 'loading' | 'done' | 'error'

const MIN_CHARS = 2
const DEBOUNCE_MS = 250

/**
 * Place autocomplete following the WAI-ARIA combobox pattern (list autocomplete, manual selection).
 * Free text is allowed: an unselected entry is sent as a `query` and geocoded server-side.
 */
export function LocationCombobox({ label, placeholder, value, onChange, client, error, action }: LocationComboboxProps) {
  const id = useId()
  const listId = `${id}-list`
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  // Last completed lookup; status is derived from whether it matches the current query.
  const [lookup, setLookup] = useState<{ query: string; results: GeocodeResult[]; failed: boolean } | null>(null)
  const [active, setActive] = useState(-1)

  const query = useDebouncedValue(value.text.trim(), DEBOUNCE_MS)
  const typing = value.text.trim().length
  const shouldSearch = open && !value.selected && query.length >= MIN_CHARS
  // Stale suggestions are hidden once the text is too short to search.
  const results = typing >= MIN_CHARS && lookup ? lookup.results : []
  const search: SearchState = !shouldSearch
    ? 'idle'
    : lookup?.query !== query
      ? 'loading'
      : lookup.failed
        ? 'error'
        : 'done'

  useEffect(() => {
    if (!shouldSearch) return
    const controller = new AbortController()
    client
      .geocode(query, controller.signal)
      .then((res) => {
        setLookup({ query, results: res.results, failed: false })
        // Nothing is pre-highlighted, so ArrowDown lands on the first suggestion (Enter alone
        // still picks it, see onKeyDown).
        setActive(-1)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setLookup({ query, results: [], failed: true })
      })
    return () => controller.abort()
  }, [client, query, shouldSearch])

  function choose(result: GeocodeResult) {
    onChange({ text: result.short_label, selected: result })
    setOpen(false)
    setActive(-1)
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) setOpen(true)
      else if (results.length) setActive((i) => (i < 0 ? 0 : (i + 1) % results.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (results.length) setActive((i) => (i <= 0 ? results.length - 1 : i - 1))
    } else if (e.key === 'Enter') {
      // Enter with nothing highlighted takes the top suggestion.
      const idx = active >= 0 ? active : results.length ? 0 : -1
      if (open && idx >= 0 && results[idx] && !value.selected) {
        e.preventDefault()
        choose(results[idx])
      }
    } else if (e.key === 'Escape') {
      if (open) {
        e.preventDefault()
        setOpen(false)
      } else if (value.text) {
        onChange({ text: '', selected: null })
      }
    }
  }

  const pending = typing >= MIN_CHARS && (query !== value.text.trim() || search === 'loading')
  const showList = open && !value.selected && typing > 0
  const status = statusMessage(search, pending, typing, results.length > 0)
  const activeId = showList && active >= 0 && results[active] ? `${id}-opt-${active}` : undefined

  return (
    <div className="relative">
      <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium text-ink-700">
        {label}
      </label>
      <div className="relative">
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          autoComplete="off"
          spellCheck={false}
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={listId}
          aria-activedescendant={activeId}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-err` : undefined}
          placeholder={placeholder}
          value={value.text}
          onChange={(e) => {
            onChange({ text: e.target.value, selected: null })
            setOpen(true)
          }}
          // A place the server already rejected shows its error inline; reopening the popover on
          // focus would repeat it and cover the next field. Typing or ArrowDown reopens it.
          onFocus={() => {
            if (!error) setOpen(true)
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          className={cn(inputClass, action ? 'pr-[5.5rem]' : 'pr-11', value.selected && 'font-medium')}
        />
        <div className="absolute inset-y-0 right-1 flex items-center gap-0.5">
          {pending && showList && <LoaderCircle className="mr-1 size-4 animate-spin text-ink-400" aria-hidden />}
          {value.text && (
            <button
              type="button"
              aria-label={`Clear ${label.toLowerCase()}`}
              onClick={() => {
                onChange({ text: '', selected: null })
                inputRef.current?.focus()
              }}
              className="grid size-9 place-items-center rounded-lg text-ink-400 hover:bg-ink-100 hover:text-ink-700"
            >
              <X className="size-4" aria-hidden />
            </button>
          )}
          {action}
        </div>
      </div>

      {error && (
        <p id={`${id}-err`} className="mt-1.5 text-xs font-medium text-danger-700">
          {error}
        </p>
      )}

      <div
        className={cn(
          'absolute inset-x-0 top-full z-30 mt-1.5 overflow-hidden rounded-xl bg-white shadow-pop ring-1 ring-ink-900/10',
          (!showList || (!results.length && !status)) && 'hidden',
        )}
        // Keep focus in the input while clicking options.
        onMouseDown={(e) => e.preventDefault()}
      >
        <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className={cn('max-h-72 overflow-auto', results.length > 0 && 'py-1')}>
          {results.map((r, i) => (
            <li
              key={`${r.lat},${r.lon},${r.label}`}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              onClick={() => choose(r)}
              onMouseMove={() => setActive(i)}
              className={cn(
                'flex min-h-11 cursor-pointer items-center gap-3 px-3 py-2',
                i === active ? 'bg-ink-100' : 'bg-white',
              )}
            >
              <MapPin className={cn('size-4 shrink-0', i === active ? 'text-hw-600' : 'text-ink-400')} aria-hidden />
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-ink-900">
                  <Highlight text={r.short_label} query={query} />
                </span>
                <span className="block truncate text-xs text-ink-500">{r.label}</span>
              </span>
              {i === 0 && active < 0 && (
                <kbd aria-hidden className="ml-auto shrink-0 rounded border border-ink-200 px-1.5 font-sans text-[10px] font-medium text-ink-500">
                  Enter
                </kbd>
              )}
            </li>
          ))}
        </ul>
        {status && (
          <div
            role="status"
            className={cn('px-3 py-2.5 text-xs text-ink-500', results.length > 0 && 'border-t border-ink-100')}
          >
            {status}
          </div>
        )}
      </div>
    </div>
  )
}

function statusMessage(state: SearchState, pending: boolean, typing: number, hasResults: boolean): ReactNode {
  if (typing < MIN_CHARS) return 'Keep typing to search US & Canada places…'
  if (pending && !hasResults) {
    return (
      <span className="flex items-center gap-2">
        <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> Searching…
      </span>
    )
  }
  if (state === 'error') {
    return (
      <span className="flex items-center gap-2">
        <WifiOff className="size-3.5 shrink-0" aria-hidden /> Search is unavailable. Keep the text; we'll look it up
        when you plan.
      </span>
    )
  }
  if (state === 'done' && !hasResults && !pending) {
    return (
      <span className="flex items-center gap-2">
        <SearchX className="size-3.5 shrink-0" aria-hidden /> No matching places. Try adding the state, e.g. “Joliet,
        IL”.
      </span>
    )
  }
  return null
}

/** Bolds the first case-insensitive occurrence of the query. */
function Highlight({ text, query }: { text: string; query: string }) {
  const i = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1
  if (i < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <mark className="bg-transparent font-semibold text-hw-700">{text.slice(i, i + query.length)}</mark>
      {text.slice(i + query.length)}
    </>
  )
}
