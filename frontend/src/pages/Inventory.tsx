import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { formatDate } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'

interface Update {
  inventory_update_id: number
  type: string
  date: string
  comment: string | null
  items: unknown[]
}

const TYPE_LABEL: Record<string, string> = {
  purchase: '➕ Purchase',
  order_usage: '➖ Order usage',
  damage: '💥 Damage',
  correction: '⚖️ Correction',
}

export default function Inventory() {
  const canEdit = useCanEdit()
  const [rows, setRows] = useState<Update[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  useEffect(() => {
    setLoading(true)
    api.get<Update[]>('/api/inventory_update')
      .then((data) => { setRows(data); setError(null) })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">Stock updates</h1>
        {canEdit && <Link to="/inventory_update/new" className="rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white">+ Stock Update</Link>}
      </div>
      <p className="mb-3 text-sm text-slate-500">
        Stock levels are shown in <Link to="/stock" className="text-violet-600 underline">📦 Stock</Link>.
      </p>
      <div className="overflow-hidden rounded-xl bg-white shadow">
        {loading && <p className="p-6 text-center text-slate-400">Loading…</p>}
        {!loading && error && (
          <p className="p-6 text-center text-red-600">Failed to load movements: {error}</p>
        )}
        {!loading && !error && rows.length === 0 && (
          <p className="p-6 text-center text-slate-400">No movements.</p>
        )}
        <ul className="divide-y divide-slate-100">
          {rows.map((u) => (
            <li key={u.inventory_update_id} onClick={() => navigate(`/inventory_update/${u.inventory_update_id}`)}
              className="flex cursor-pointer items-center gap-3 p-3 hover:bg-violet-50">
              <div className="flex-1">
                <div className="font-semibold">{TYPE_LABEL[u.type] ?? u.type}</div>
                <div className="text-sm text-slate-500">{formatDate(u.date)} · {u.items.length} lines{u.comment ? ` · ${u.comment}` : ''}</div>
              </div>
              <span className="text-slate-300">›</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
