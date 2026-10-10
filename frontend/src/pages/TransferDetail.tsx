import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, CalendarDays, CreditCard, Pencil } from 'lucide-react'
import { api } from '../api'
import { formatDate, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'

interface Transfer {
  money_transfer_id: number
  from_party_id: number
  to_party_id: number
  date: string
  amount: string
  payment_method: string | null
  comment: string | null
}

export default function TransferDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const canEdit = useCanEdit()
  const [t, setT] = useState<Transfer | null>(null)
  const [error, setError] = useState('')
  const parties = useOptions<{ party_id: number; name: string }>('/api/party')
  const partyName = (i: number) => parties.find((p) => p.party_id === i)?.name ?? `#${i}`

  useEffect(() => {
    api.get<Transfer>(`/api/money_transfer/${id}`).then(setT).catch((e) => setError(e.message))
  }, [id])

  if (error) return <p className="p-3 text-sm text-red-600">{error}</p>
  if (!t) return <p className="p-6 text-center text-slate-400">Loading…</p>

  return (
    <div className="p-3">
      {/* amount headline */}
      <div className="mb-3 rounded-xl bg-white p-4 text-center shadow">
        <div className="text-3xl font-bold">{t.amount}€</div>
        <div className="mt-2 flex items-center justify-center gap-2 text-sm">
          <span className="rounded-full bg-violet-100 px-2.5 py-0.5 font-semibold text-violet-800">{partyName(t.from_party_id)}</span>
          <ArrowRight size={16} className="text-slate-400" />
          <span className="rounded-full bg-violet-100 px-2.5 py-0.5 font-semibold text-violet-800">{partyName(t.to_party_id)}</span>
        </div>
      </div>

      <div className="space-y-2 rounded-xl bg-white p-3 shadow">
        <div className="flex items-center gap-2 text-sm">
          <CalendarDays size={16} className="shrink-0 text-slate-400" />
          <span>{formatDate(t.date)}</span>
        </div>
        {t.payment_method && (
          <div className="flex items-center gap-2 text-sm">
            <CreditCard size={16} className="shrink-0 text-slate-400" />
            <span>{t.payment_method}</span>
          </div>
        )}
        {t.comment && <div className="text-xs italic text-slate-400">{t.comment}</div>}
      </div>

      {canEdit && (
        <button onClick={() => navigate(`/transfer/${id}/edit`)}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-violet-600 p-3 font-semibold text-white">
          <Pencil size={18} /> Edit
        </button>
      )}
    </div>
  )
}
