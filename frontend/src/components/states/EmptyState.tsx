import { CalendarDays, MapPinned, Route, Sparkles } from 'lucide-react'
import { Button, Card } from '../ui'

const STEPS = [
  {
    icon: MapPinned,
    title: 'Enter the load',
    body: 'Where the truck is, the pickup and the dropoff, plus hours already used in your 70-hour/8-day cycle.',
  },
  {
    icon: Route,
    title: 'We schedule every stop',
    body: '30-minute breaks after 8 h driving, 10-hour rests at the 11/14-hour limits, fuel every 1,000 mi, 34-hour restarts.',
  },
  {
    icon: CalendarDays,
    title: 'Get filled-out logs',
    body: "One FMCSA driver's daily log per calendar day, with the duty graph, remarks and 70-hour recap. Print or export.",
  },
]

export function EmptyState({ onLoadSample }: { onLoadSample: () => void }) {
  return (
    <Card className="overflow-hidden">
      <div className="grid gap-6 p-6 sm:p-8 lg:grid-cols-[1fr_auto] lg:items-center">
        <div>
          <p className="text-[11px] font-semibold tracking-[0.14em] text-hw-700 uppercase">How it works</p>
          <h2 className="mt-1 max-w-xl font-display text-2xl leading-tight font-extrabold tracking-tight text-ink-900">
            From three addresses to a legal, logged trip in one click.
          </h2>
        </div>
        <Button variant="primary" onClick={onLoadSample} icon={<Sparkles className="size-4 text-hw-300" aria-hidden />}>
          See a sample trip
        </Button>
      </div>
      <ol className="grid gap-px border-t border-ink-150 bg-ink-150 md:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="bg-white p-6 sm:p-8">
            <div className="flex items-center gap-3">
              <span className="grid size-9 place-items-center rounded-lg bg-ink-900 text-white">
                <s.icon className="size-[18px]" aria-hidden />
              </span>
              <span className="font-mono text-xs font-semibold text-ink-400">0{i + 1}</span>
            </div>
            <h3 className="mt-4 font-display text-base font-bold text-ink-900">{s.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-600">{s.body}</p>
          </li>
        ))}
      </ol>
    </Card>
  )
}
