// localStorage access that never throws (private mode, blocked storage, quota).

export function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? { ...fallback, ...(JSON.parse(raw) as Partial<T>) } : fallback
  } catch {
    return fallback
  }
}

export function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Persisting is a convenience; ignore failures.
  }
}
