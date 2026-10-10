// Reference-data cache shared by `useOptions` (reads) and `api` (invalidation).
//
// Dropdown lists (parties, products, categories, colours…) change rarely but
// were re-fetched on every page navigation, which is painfully slow when the
// server and DB are far apart. We cache each URL's result in memory for a short
// TTL and de-duplicate concurrent requests, so navigating feels instant. Any
// write through `api` clears the cache so the next read is fresh.
import { api } from '../api'

const TTL_MS = 5 * 60 * 1000 // 5 minutes
type Entry = { at: number; promise: Promise<unknown[]> }
const cache = new Map<string, Entry>()

export function fetchOptions<T>(url: string): Promise<T[]> {
  const hit = cache.get(url)
  if (hit && Date.now() - hit.at < TTL_MS) return hit.promise as Promise<T[]>
  const promise = api.get<T[]>(url).catch((e) => {
    cache.delete(url) // don't cache failures — allow a retry on next mount
    throw e
  })
  cache.set(url, { at: Date.now(), promise })
  return promise as Promise<T[]>
}

/** Drop cached reference data (all URLs, or those whose key contains `match`). */
export function invalidateOptions(match?: string): void {
  if (!match) { cache.clear(); return }
  for (const key of cache.keys()) if (key.includes(match)) cache.delete(key)
}