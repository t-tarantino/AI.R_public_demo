import { useMemo, useRef, useState } from 'react'
import { ChevronDown, Search, X } from 'lucide-react'

// A searchable single-select (combobox). Built because the plain <select> for
// products had grown unusable: hundreds of SKUs, impossible to scan. Here the
// caller passes options already sorted/grouped (e.g. recent first); we add the
// text filter, grouping headers and a tap-to-pick panel. Mobile-first.
export interface SearchOption {
  value: number
  label: string
  keywords?: string   // extra searchable text (code, colour…) not shown but matched
  badge?: string      // short trailing tag, e.g. '⭐' for first-choice
  group?: string      // optional section header; consecutive equal groups merge
}

interface Props {
  value: number | ''
  onChange: (v: number | '') => void
  options: SearchOption[]
  placeholder?: string
  className?: string
}

export default function SearchSelect({ value, onChange, options, placeholder = '— choose —', className }: Props) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const selected = options.find((o) => o.value === value)

  const filtered = useMemo(() => {
    const tokens = q.toLowerCase().split(/\s+/).filter(Boolean)
    if (tokens.length === 0) return options
    return options.filter((o) => {
      const hay = `${o.label} ${o.keywords ?? ''}`.toLowerCase()
      return tokens.every((t) => hay.includes(t))
    })
  }, [options, q])

  const openPanel = () => { setOpen(true); setQ(''); setTimeout(() => inputRef.current?.focus(), 30) }
  const pick = (v: number | '') => { onChange(v); setOpen(false) }

  return (
    <div className={`relative ${className ?? ''}`}>
      <button type="button" onClick={openPanel}
        className="flex w-full items-center gap-2 rounded-lg border border-slate-300 bg-white p-2 text-left">
        <span className={`min-w-0 flex-1 truncate ${selected ? '' : 'text-slate-400'}`}>
          {selected ? selected.label : placeholder}
        </span>
        {selected?.badge && <span className="shrink-0 text-sm">{selected.badge}</span>}
        <ChevronDown size={16} className="shrink-0 text-slate-400" />
      </button>

      {open && (
        <>
          {/* backdrop: a tap anywhere outside closes the panel */}
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute left-0 right-0 z-30 mt-1 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
            <div className="flex items-center gap-2 border-b border-slate-100 p-2">
              <Search size={15} className="shrink-0 text-slate-400" />
              <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="Search…" className="min-w-0 flex-1 outline-none" />
              {q && <button type="button" onClick={() => setQ('')} className="shrink-0 text-slate-400"><X size={15} /></button>}
            </div>
            <div className="max-h-64 overflow-y-auto">
              {/* clear choice */}
              <button type="button" onClick={() => pick('')}
                className="block w-full px-3 py-2 text-left text-sm text-slate-400 hover:bg-slate-50">
                {placeholder}
              </button>
              {filtered.length === 0 ? (
                <p className="px-3 py-3 text-center text-sm text-slate-400">No match.</p>
              ) : filtered.map((o, i) => {
                const newGroup = o.group && o.group !== filtered[i - 1]?.group
                return (
                  <div key={o.value}>
                    {newGroup && (
                      <div className="bg-slate-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                        {o.group}
                      </div>
                    )}
                    <button type="button" onClick={() => pick(o.value)}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-violet-50 ${o.value === value ? 'bg-violet-50 font-medium' : ''}`}>
                      <span className="min-w-0 flex-1 truncate">{o.label}</span>
                      {o.badge && <span className="shrink-0">{o.badge}</span>}
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
