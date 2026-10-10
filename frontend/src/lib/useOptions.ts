import { useEffect, useState } from 'react'
import { fetchOptions } from './optionsCache'

export { invalidateOptions } from './optionsCache'

// Fetch a list (cached) and expose it as select options.
export function useOptions<T = Record<string, unknown>>(url: string): T[] {
  const [options, setOptions] = useState<T[]>([])
  useEffect(() => {
    let alive = true
    fetchOptions<T>(url)
      .then((data) => { if (alive) setOptions(data) })
      .catch((e) => {
        // Non-blocking (these feed dropdowns), but log so failures are diagnosable.
        console.error(`useOptions: failed to load ${url}:`, e)
      })
    return () => { alive = false }
  }, [url])
  return options
}

export const STATE_LABELS: Record<string, string> = {
  draft: 'Draft',
  confirmed: 'Confirmed',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export const STATE_COLOR: Record<string, string> = {
  draft: 'bg-slate-200 text-slate-600',
  confirmed: 'bg-sky-100 text-sky-700',
  completed: 'bg-green-100 text-green-700',
  cancelled: 'bg-red-100 text-red-600',
}

// Format an ISO date (YYYY-MM-DD) as e.g. "Fri, 26 Sep 2026".
// Dates are shown DD/MM/YYYY everywhere.
export const formatDate = (iso: string) => {
  const d = new Date(iso + 'T00:00:00')
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`
}

// "Fri 26/09/2026" — used on the history group headers.
export const formatDateWithDay = (iso: string) => {
  const d = new Date(iso + 'T00:00:00')
  return `${d.toLocaleDateString('en-GB', { weekday: 'short' })} ${formatDate(iso)}`
}

// Rows imported by AI.Richie carry a "[richie]" provenance marker (older ones
// "[richie:xxxx]") in their comment. Show a friendly note instead.
export const displayComment = (comment: string | null | undefined, noun = 'Order'): string | null => {
  if (!comment || /^\[(import|registro)/i.test(comment)) return null
  if (!/\[richie(?::[^\]]*)?\]/.test(comment)) return comment
  const rest = comment.replace(/\s*\[richie(?::[^\]]*)?\]\s*/g, ' ').trim()
  return rest
    ? `${noun} written by AI.Richie. Comment: ${rest}`
    : `${noun} written by AI.Richie, no additional comments`
}
