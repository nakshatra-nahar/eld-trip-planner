// Single source of truth for duty-status colors and per-activity presentation.
// Used by the map markers, itinerary, duty timeline bar and legends.
import {
  BedDouble,
  ClipboardCheck,
  ClipboardList,
  Coffee,
  Flag,
  Fuel,
  type LucideIcon,
  Navigation,
  Package,
  RotateCcw,
  Truck,
} from 'lucide-react'
import type { DutyStatus, EventKind } from '../types/api'

export interface StatusMeta {
  label: string
  short: string
  /** Line number on the FMCSA graph grid. */
  line: 1 | 2 | 3 | 4
  color: string
  soft: string
  /** Tailwind classes for chips: soft background, strong text. */
  chip: string
  dot: string
}

export const DUTY_STATUS: Record<DutyStatus, StatusMeta> = {
  OFF: {
    label: 'Off duty',
    short: 'OFF',
    line: 1,
    color: 'var(--color-duty-off)',
    soft: 'var(--color-duty-off-soft)',
    chip: 'bg-duty-off-soft text-[#475569] ring-duty-off/25',
    dot: 'bg-duty-off',
  },
  SB: {
    label: 'Sleeper berth',
    short: 'SB',
    line: 2,
    color: 'var(--color-duty-sb)',
    soft: 'var(--color-duty-sb-soft)',
    chip: 'bg-duty-sb-soft text-[#4338ca] ring-duty-sb/25',
    dot: 'bg-duty-sb',
  },
  D: {
    label: 'Driving',
    short: 'D',
    line: 3,
    color: 'var(--color-duty-d)',
    soft: 'var(--color-duty-d-soft)',
    chip: 'bg-duty-d-soft text-[#047857] ring-duty-d/25',
    dot: 'bg-duty-d',
  },
  ON: {
    label: 'On duty (not driving)',
    short: 'ON',
    line: 4,
    color: 'var(--color-duty-on)',
    soft: 'var(--color-duty-on-soft)',
    chip: 'bg-duty-on-soft text-[#92400e] ring-duty-on/25',
    dot: 'bg-duty-on',
  },
}

/** Raw hex values for contexts that cannot read CSS variables (MapLibre paint, canvas). */
export const DUTY_HEX: Record<DutyStatus, string> = {
  OFF: '#64748b',
  SB: '#4f46e5',
  D: '#059669',
  ON: '#d97706',
}

export const DUTY_ORDER: DutyStatus[] = ['OFF', 'SB', 'D', 'ON']

export interface KindMeta {
  label: string
  icon: LucideIcon
  /** Lower number = more important when several stops share a map location. */
  priority: number
}

export const EVENT_KIND: Record<EventKind, KindMeta> = {
  drive: { label: 'Driving', icon: Truck, priority: 9 },
  pickup: { label: 'Pickup', icon: Package, priority: 0 },
  dropoff: { label: 'Dropoff', icon: Flag, priority: 0 },
  restart: { label: '34-hour restart', icon: RotateCcw, priority: 1 },
  rest: { label: '10-hour rest', icon: BedDouble, priority: 2 },
  fuel: { label: 'Fuel stop', icon: Fuel, priority: 3 },
  break: { label: '30-minute break', icon: Coffee, priority: 4 },
  pre_trip: { label: 'Pre-trip inspection', icon: ClipboardList, priority: 5 },
  post_trip: { label: 'Post-trip inspection', icon: ClipboardCheck, priority: 6 },
}

export const ROLE_ICON = {
  current: Navigation,
  pickup: Package,
  dropoff: Flag,
} as const

/**
 * Why a stop was scheduled ("Required: 11-hour driving limit reached"), when the API sends it.
 * Read defensively: `reason` is an optional, additive field on timeline events and stops.
 */
export function stopReason(item: object): string | undefined {
  const reason = (item as { reason?: unknown }).reason
  return typeof reason === 'string' && reason.trim() ? reason.trim() : undefined
}
