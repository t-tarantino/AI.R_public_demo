import { useLayoutEffect, useMemo, useRef, useState } from 'react'

export type Range = [string, string]
type Mode = 'week' | 'month' | 'year'

const MODES: { key: Mode; label: string }[] = [
  { key: 'week', label: 'Week' },
  { key: 'month', label: 'Month' },
  { key: 'year', label: 'Year' },
]

// Local-time ISO date (toISOString would shift the day in positive UTC offsets).
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const parse = (s: string) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d) }

interface Option { key: string; label: string; sub?: string; range: Range }

function weekOf(d: Date): Range {
  const day = (d.getDay() + 6) % 7 // Monday-based week
  return [iso(new Date(d.getFullYear(), d.getMonth(), d.getDate() - day)),
          iso(new Date(d.getFullYear(), d.getMonth(), d.getDate() - day + 6))]
}
const monthOf = (d: Date): Range =>
  [iso(new Date(d.getFullYear(), d.getMonth(), 1)), iso(new Date(d.getFullYear(), d.getMonth() + 1, 0))]
const yearOf = (d: Date): Range => [`${d.getFullYear()}-01-01`, `${d.getFullYear()}-12-31`]

const rangeOf = (mode: Mode, d: Date): Range =>
  mode === 'week' ? weekOf(d) : mode === 'month' ? monthOf(d) : yearOf(d)

/** The current month — the pages' default period. */
export const currentMonthRange = (): Range => monthOf(new Date())

// How far back / forward the scroller reaches around the present.
const SPAN: Record<Mode, [number, number]> = { week: [-52, 26], month: [-24, 12], year: [-5, 2] }

function buildOptions(mode: Mode): Option[] {
  const now = new Date()
  const [back, fwd] = SPAN[mode]
  const out: Option[] = []
  for (let i = back; i <= fwd; i++) {
    if (mode === 'week') {
      const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i * 7)
      const range = weekOf(d)
      const a = parse(range[0]); const b = parse(range[1])
      const mon = (x: Date) => x.toLocaleDateString('en-GB', { month: 'short' })
      const label = a.getMonth() === b.getMonth()
        ? `${a.getDate()}–${b.getDate()} ${mon(b)}`
        : `${a.getDate()} ${mon(a)} – ${b.getDate()} ${mon(b)}`
      out.push({ key: range[0], label, sub: String(b.getFullYear()), range })
    } else if (mode === 'month') {
      const d = new Date(now.getFullYear(), now.getMonth() + i, 1)
      out.push({ key: iso(d), label: d.toLocaleDateString('en-GB', { month: 'short' }), sub: String(d.getFullYear()), range: monthOf(d) })
    } else {
      const d = new Date(now.getFullYear() + i, 0, 1)
      out.push({ key: iso(d), label: String(d.getFullYear()), range: yearOf(d) })
    }
  }
  return out
}

export default function PeriodFilter({ start, end, onChange }: {
  start: string; end: string; onChange: (r: Range) => void
}) {
  const [mode, setMode] = useState<Mode>('month')
  const options = useMemo(() => buildOptions(mode), [mode])
  const scroller = useRef<HTMLDivElement>(null)
  const firstRun = useRef(true)

  const activeKey = options.find((o) => o.range[0] === start && o.range[1] === end)?.key

  // Keep the selected period (by default: the present) centred in the scroller.
  useLayoutEffect(() => {
    const box = scroller.current
    const el = box?.querySelector<HTMLElement>('[data-active="true"]')
    if (!box || !el) return
    const left = el.offsetLeft - (box.clientWidth - el.offsetWidth) / 2
    box.scrollTo({ left, behavior: firstRun.current ? 'auto' : 'smooth' })
    firstRun.current = false
  }, [activeKey, mode])

  const switchMode = (m: Mode) => {
    if (m === mode) return
    setMode(m)
    onChange(rangeOf(m, new Date())) // always jump to the present Week/Month/Year
  }

  return (
    <>
      <div className="mb-2 flex flex-wrap gap-2">
        {MODES.map((m) => (
          <button key={m.key} onClick={() => switchMode(m.key)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${mode === m.key ? 'bg-violet-600 text-white' : 'bg-white text-slate-600 shadow'}`}>
            {m.label}
          </button>
        ))}
      </div>
      <div ref={scroller} className="relative mb-2 flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {options.map((o) => {
          const active = o.key === activeKey
          return (
            <button key={o.key} data-active={active} onClick={() => onChange(o.range)}
              className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-center text-sm font-medium leading-tight ${active ? 'bg-violet-600 text-white' : 'bg-white text-slate-600 shadow'}`}>
              {o.label}
              {o.sub && <span className={`block text-[10px] ${active ? 'text-violet-200' : 'text-slate-400'}`}>{o.sub}</span>}
            </button>
          )
        })}
      </div>
      <div className="mb-3 flex items-center gap-2 text-sm">
        <input type="date" value={start} onChange={(e) => onChange([e.target.value, end])}
          className="rounded-lg border border-slate-300 bg-white p-2" />
        <span className="text-slate-400">→</span>
        <input type="date" value={end} onChange={(e) => onChange([start, e.target.value])}
          className="rounded-lg border border-slate-300 bg-white p-2" />
      </div>
    </>
  )
}
