import { Card, Skeleton } from '../ui'

export function ResultsSkeleton() {
  return (
    <Card aria-busy aria-label="Loading trip results">
      <div className="border-b border-ink-150 px-6 py-3">
        <Skeleton className="h-10 w-80 max-w-full rounded-xl" />
      </div>
      <div className="grid gap-4 px-6 py-6">
        <Skeleton className="h-5 w-56" />
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="grid grid-cols-[4rem_2rem_1fr] items-start gap-3">
            <Skeleton className="h-4 w-12 justify-self-end" />
            <Skeleton className="size-7 rounded-full" />
            <div className="grid gap-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}
