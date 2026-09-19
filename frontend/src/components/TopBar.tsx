import { ShieldCheck } from 'lucide-react'
import { Badge } from './ui'

export function TopBar({ demo }: { demo: boolean }) {
  return (
    <header
      data-print-hide
      className="sticky top-0 z-40 border-b border-white/5 bg-ink-900/95 text-white backdrop-blur supports-[backdrop-filter]:bg-ink-900/90"
    >
      <div className="mx-auto flex h-[60px] max-w-[1600px] items-center gap-3 px-4 sm:px-6">
        <a href="./" className="flex items-center gap-2.5 rounded-lg" aria-label="RouteLog home">
          <LogoMark />
          <span className="font-display text-[19px] font-extrabold tracking-tight">
            Route<span className="text-hw-400">Log</span>
          </span>
        </a>
        <span className="hidden h-5 w-px bg-white/15 sm:block" aria-hidden />
        <p className="hidden text-[13px] text-ink-300 md:block">HOS trip planner &amp; ELD log sheets</p>
        <div className="ml-auto flex items-center gap-2">
          {demo && <Badge tone="accent">Demo data</Badge>}
          <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-white/[0.07] px-2.5 text-[11px] font-medium text-ink-200 ring-1 ring-white/10">
            <ShieldCheck className="size-3.5 text-hw-400" aria-hidden />
            <span className="sm:hidden">70h/8-day</span>
            <span className="hidden sm:inline">FMCSA 70h/8-day · Property-carrying</span>
          </span>
        </div>
      </div>
    </header>
  )
}

/** Two converging road edges with an orange dashed center line. */
function LogoMark() {
  return (
    <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="#1a2540" />
      <path d="M9 25 L14 7 M23 25 L18 7" stroke="#bcc3d2" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M16 9v3M16 15v3M16 21v3" stroke="#ef6c11" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}
