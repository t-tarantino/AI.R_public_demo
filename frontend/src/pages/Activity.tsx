import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { formatDate } from '../lib/useOptions'

interface ActivityRow {
  audit_log_id: number
  username: string
  action: string
  entity: string
  category: string
  entity_id: number | null
  changes: string | null
  timestamp: string
}

const ACTION_LABEL: Record<string, { text: string; tint: string }> = {
  create: { text: 'created', tint: 'bg-green-100 text-green-700' },
  update: { text: 'edited', tint: 'bg-amber-100 text-amber-700' },
  deactivate: { text: 'deactivated', tint: 'bg-slate-200 text-slate-600' },
  delete: { text: 'deleted', tint: 'bg-red-100 text-red-700' },
}

// entity → { readable label, optional detail-page path builder }
const ENTITY: Record<string, { label: string; to?: (id: number) => string }> = {
  customer_order: { label: 'Order', to: (id) => `/order/${id}` },
  expense: { label: 'Expense', to: (id) => `/expense/${id}` },
  work: { label: 'Work hours', to: (id) => `/work/${id}` },
  money_transfer: { label: 'Transfer', to: (id) => `/transfer/${id}` },
  inventory_update: { label: 'Stock movement' },
  party: { label: 'Party' },
  location: { label: 'Location' },
  color: { label: 'Color' },
  composition: { label: 'Composition' },
  composition_bom: { label: 'Bill of materials' },
  expense_category: { label: 'Expense category' },
  required_item: { label: 'Item' },
  product: { label: 'Product' },
  stock_threshold: { label: 'Stock threshold' },
}

const TABS = [
  { key: 'operations', label: 'Operations' },
  { key: 'master', label: 'Master data' },
]

// Render the stored `changes` JSON as readable lines.
// Update payloads look like { field: { da: old, a: new } }; creates often carry
// a small summary like { items: 3 }.
function ChangeLines({ raw }: { raw: string }) {
  let parsed: Record<string, unknown>
  try { parsed = JSON.parse(raw) } catch { return <pre className="text-xs text-slate-500">{raw}</pre> }
  const fmt = (v: unknown) => (v === null || v === '' ? '—' : String(v))
  return (
    <ul className="mt-2 space-y-1 border-t border-slate-100 pt-2 text-xs text-slate-600">
      {Object.entries(parsed).map(([field, val]) => {
        const isDiff = val && typeof val === 'object' && 'da' in (val as object) && 'a' in (val as object)
        return (
          <li key={field}>
            <span className="font-medium text-slate-500">{field}:</span>{' '}
            {isDiff ? (
              <>
                <span className="text-slate-400 line-through">{fmt((val as { da: unknown }).da)}</span>
                <span className="mx-1 text-slate-400">→</span>
                <span className="font-medium text-slate-700">{fmt((val as { a: unknown }).a)}</span>
              </>
            ) : (
              <span className="text-slate-700">{fmt(val)}</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export default function Activity() {
  const [rows, setRows] = useState<ActivityRow[]>([])
  const [tab, setTab] = useState('operations')
  const [entity, setEntity] = useState('')
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    setEntity('')
    api.get<ActivityRow[]>(`/api/activity?category=${tab}`).then(setRows).catch((e) => setError(e.message))
  }, [tab])

  // entity sub-filter, populated from what's actually present
  const entities = useMemo(
    () => [...new Set(rows.map((r) => r.entity))].sort((a, b) =>
      (ENTITY[a]?.label ?? a).localeCompare(ENTITY[b]?.label ?? b)),
    [rows])

  const shown = entity ? rows.filter((r) => r.entity === entity) : rows

  // group by calendar day for a register-like reading
  const byDate = useMemo(() => {
    const m = new Map<string, ActivityRow[]>()
    for (const r of shown) {
      const d = r.timestamp.slice(0, 10)
      const l = m.get(d) ?? []; l.push(r); m.set(d, l)
    }
    return [...m.entries()]
  }, [shown])

  return (
    <div className="p-3">
      <h1 className="mb-1 text-xl font-bold">Activity</h1>
      <p className="mb-3 text-sm text-slate-500">Register of data changes — what changed, when and by whom.</p>

      {/* category tabs */}
      <div className="mb-3 flex gap-2">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${tab === t.key ? 'bg-violet-600 text-white' : 'bg-white text-slate-600 shadow'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* entity sub-filter */}
      {entities.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-2">
          <button onClick={() => setEntity('')}
            className={`rounded-full px-2.5 py-1 text-xs font-medium ${entity === '' ? 'bg-violet-100 text-violet-700 ring-1 ring-violet-200' : 'bg-white text-slate-500 shadow'}`}>
            All
          </button>
          {entities.map((e) => (
            <button key={e} onClick={() => setEntity(e)}
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${entity === e ? 'bg-violet-100 text-violet-700 ring-1 ring-violet-200' : 'bg-white text-slate-500 shadow'}`}>
              {ENTITY[e]?.label ?? e}
            </button>
          ))}
        </div>
      )}

      {error && <p className="mb-2 rounded-xl bg-red-50 p-3 text-sm text-red-600 shadow ring-1 ring-red-200">{error}</p>}
      {byDate.length === 0 && !error && (
        <p className="rounded-xl bg-white p-4 text-sm text-slate-400 shadow">No changes recorded yet.</p>
      )}

      <div className="space-y-4">
        {byDate.map(([date, dayRows]) => (
          <section key={date} className="overflow-hidden rounded-xl bg-white shadow">
            <div className="bg-gradient-to-r from-violet-500 to-sky-400 px-3 py-2">
              <span className="rounded-full bg-white/25 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-white">
                {formatDate(date)}
              </span>
            </div>
            <ul className="divide-y divide-slate-100">
              {dayRows.map((r) => {
                const meta = ENTITY[r.entity] ?? { label: r.entity }
                const act = ACTION_LABEL[r.action] ?? { text: r.action, tint: 'bg-slate-100 text-slate-600' }
                const open = expanded === r.audit_log_id
                const link = meta.to && r.entity_id !== null ? meta.to(r.entity_id) : undefined
                return (
                  <li key={r.audit_log_id} className="px-3 py-2.5">
                    <div className="flex cursor-pointer items-start gap-2"
                      onClick={() => setExpanded(open ? null : r.audit_log_id)}>
                      <span className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${act.tint}`}>
                        {act.text}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm">
                          <span className="font-semibold">{meta.label}</span>
                          {r.entity_id !== null && (
                            link ? (
                              <button onClick={(e) => { e.stopPropagation(); navigate(link) }}
                                className="ml-1 font-medium text-violet-600 hover:underline">#{r.entity_id}</button>
                            ) : <span className="ml-1 text-slate-500">#{r.entity_id}</span>
                          )}
                        </div>
                        <div className="text-xs text-slate-400">
                          by {r.username} · {new Date(r.timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    </div>
                    {open && r.changes && <ChangeLines raw={r.changes} />}
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}
