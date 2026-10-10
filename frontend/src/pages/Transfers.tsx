import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { api } from '../api'
import { useCanEdit } from '../lib/user'
import { formatDate, useOptions } from '../lib/useOptions'

interface Transfer {
  money_transfer_id: number
  from_party_id: number
  to_party_id: number
  date: string
  amount: string
  payment_method: string | null
  comment: string | null
}

export default function Transfers() {
  const canEdit = useCanEdit()
  const [rows, setRows] = useState<Transfer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const parties = useOptions<{ party_id: number; name: string }>('/api/party')
  const partyName = (id: number) => parties.find((p) => p.party_id === id)?.name ?? `#${id}`

  useEffect(() => {
    setLoading(true)
    api.get<Transfer[]>('/api/money_transfer')
      .then((data) => { setRows(data); setError(null) })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">Money transfers</h1>
        {canEdit && <Link to="/transfer/new" className="rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white">+ Money Transfer</Link>}
      </div>

      {loading && <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">Loading…</p>}
      {!loading && error && (
        <p className="rounded-xl bg-white p-6 text-center text-red-600 shadow">Failed to load transfers: {error}</p>
      )}
      {!loading && !error && rows.length === 0 && (
        <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">No transfers recorded.</p>
      )}

      <ul className="space-y-2">
        {rows.map((t) => (
          <li key={t.money_transfer_id}>
            <div
              onClick={() => navigate(`/transfer/${t.money_transfer_id}`)}
              className="flex cursor-pointer items-center justify-between rounded-xl bg-white p-3 shadow hover:bg-violet-50"
            >
              <div>
                <div className="font-semibold">{partyName(t.from_party_id)} → {partyName(t.to_party_id)}</div>
                <div className="text-sm text-slate-500">{formatDate(t.date)}{t.comment ? ` · ${t.comment}` : ''}</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-semibold">{t.amount}€</span>
                <ChevronRight size={15} className="text-slate-300" />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
