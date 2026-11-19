/** Lightweight sessionStorage Stale-While-Revalidate (SWR) cache for instant tab switches & refreshes. */

const PREFIX = 'algoxen_swr_v1:'

interface SwrEntry<T> {
  ts: number
  data: T
}

export function readSwr<T>(key: string, maxAgeMs = 10 * 60 * 1000): SwrEntry<T> | null {
  try {
    const raw = window.sessionStorage.getItem(PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as SwrEntry<T>
    if (!parsed || typeof parsed.ts !== 'number') return null
    if (Date.now() - parsed.ts > maxAgeMs) return null
    return parsed
  } catch {
    return null
  }
}

export function writeSwr<T>(key: string, data: T): void {
  try {
    const entry: SwrEntry<T> = { ts: Date.now(), data }
    window.sessionStorage.setItem(PREFIX + key, JSON.stringify(entry))
  } catch {
    /* ignore storage quota / private-mode errors */
  }
}

export function bustSwr(keyPrefix: string): void {
  try {
    const full = PREFIX + keyPrefix
    for (let i = window.sessionStorage.length - 1; i >= 0; i--) {
      const k = window.sessionStorage.key(i)
      if (k && k.startsWith(full)) {
        window.sessionStorage.removeItem(k)
      }
    }
  } catch {
    /* ignore */
  }
}
