import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useOptions } from '../lib/useOptions'

interface Header {
  from_party_id: number | ''
  to_party_id: number | ''
  date: string
  amount: string
  payment_method: string
  comment: string
}

const emptyHeader: Header = {
  from_party_id: '', to_party_id: '', date: new Date().toISOString().slice(0, 10),
  amount: '', payment_method: '', comment: '',
}
const inputCls = 'mt-1 w-full rounded-lg border border-slate-300 bg-white p-3'

export default function TransferForm() {
  const { id } = useParams()
  const isNew = id === undefined
  const navigate = useNavigate()
  const [header, setHeader] = useState<Header>(emptyHeader)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [existing, setExisting] = useState<{ money_transfer_id: number; from_party_id: number; to_party_id: number; date: string; amount: string }[]>([])

  const parties = useOptions<{ party_id: number; name: string }>('/api/party')

  useEffect(() => {
    api.get<{ money_transfer_id: number; from_party_id: number; to_party_id: number; date: string; amount: string }[]>('/api/money_transfer')
      .then(setExisting).catch(() => {})
  }, [])

  useEffect(() => {
    if (isNew) return
    api.get<Record<string, unknown>>(`/api/money_transfer/${id}`).then((t) => {
      setHeader({
        from_party_id: t.from_party_id as number,
        to_party_id: t.to_party_id as number,
        date: t.date as string,
        amount: String(t.amount),
        payment_method: (t.payment_method as string) ?? '',
        comment: (t.comment as string) ?? '',
      })
    }).catch((e) => setError(e.message))
  }, [id, isNew])

  const save = async () => {
    setBusy(true); setError('')
    if (header.from_party_id !== '' && header.from_party_id === header.to_party_id) {
      setError('"From" and "To" must be different parties.')
      setBusy(false)
      return
    }
    const body = {
      from_party_id: header.from_party_id,
      to_party_id: header.to_party_id,
      date: header.date,
      amount: header.amount.replace(',', '.'),   // accept comma decimals (IT mobile)
      payment_method: header.payment_method || null,
      comment: header.comment || null,
    }
    try {
      if (isNew) {
        await api.post('/api/money_transfer', body)
      } else {
        await api.patch(`/api/money_transfer/${id}`, body)
      }
      navigate('/transfer')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!confirm('Delete this money transfer? This cannot be undone.')) return
    setBusy(true); setError('')
    try {
      await api.delete(`/api/money_transfer/${id}`)
      navigate('/transfer')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setBusy(false) }
  }

  // possible duplicate: identical parties, date and amount
  const dup = header.from_party_id !== '' && header.to_party_id !== '' && header.date && header.amount !== ''
    ? existing.find((t) => t.from_party_id === header.from_party_id && t.to_party_id === header.to_party_id
        && t.date === header.date && Number(t.amount) === Number(header.amount.replace(',', '.'))
        && t.money_transfer_id !== Number(id))
    : undefined

  return (
    <div className="p-3">
      <h1 className="mb-4 text-xl font-bold">{isNew ? 'New money transfer' : 'Money transfer'}</h1>
      <p className="mb-4 text-sm text-slate-500">
        A plain cash movement between two parties — used to settle a debt (e.g. a
        reimbursement, or a customer paying off order revenue). Not an expense, not a sale.
      </p>
      <div className="space-y-4 rounded-xl bg-white p-4 shadow">
        <label className="block"><span className="text-sm font-medium">From (who paid) *</span>
          <select className={inputCls} value={header.from_party_id}
            onChange={(e) => setHeader({ ...header, from_party_id: e.target.value === '' ? '' : Number(e.target.value) })}>
            <option value="">— choose —</option>
            {parties.map((p) => <option key={p.party_id} value={p.party_id}>{p.name}</option>)}
          </select>
        </label>
        <label className="block"><span className="text-sm font-medium">To (who received) *</span>
          <select className={inputCls} value={header.to_party_id}
            onChange={(e) => setHeader({ ...header, to_party_id: e.target.value === '' ? '' : Number(e.target.value) })}>
            <option value="">— choose —</option>
            {parties.map((p) => <option key={p.party_id} value={p.party_id}>{p.name}</option>)}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block"><span className="text-sm font-medium">Date *</span>
            <input type="date" className={inputCls} value={header.date}
              onChange={(e) => setHeader({ ...header, date: e.target.value })} />
          </label>
          <label className="block"><span className="text-sm font-medium">Amount € *</span>
            <input className={inputCls} inputMode="decimal" value={header.amount}
              onChange={(e) => setHeader({ ...header, amount: e.target.value })} />
          </label>
        </div>
        <label className="block"><span className="text-sm font-medium">Payment method</span>
          <input className={inputCls} value={header.payment_method} placeholder="card / cash / transfer…"
            onChange={(e) => setHeader({ ...header, payment_method: e.target.value })} />
        </label>
        <label className="block"><span className="text-sm font-medium">Notes</span>
          <textarea className={inputCls} rows={2} value={header.comment}
            placeholder="e.g. what debt this settles"
            onChange={(e) => setHeader({ ...header, comment: e.target.value })} />
        </label>
      </div>

      {dup && (
        <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-700 ring-1 ring-amber-200">
          ⚠ Possible duplicate: an identical transfer already exists (same parties, date and amount) — #{dup.money_transfer_id}.
        </p>
      )}
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex gap-3">
        <button onClick={save} disabled={busy}
          className="flex-1 rounded-lg bg-violet-600 p-3 font-semibold text-white disabled:opacity-50">
          {busy ? 'Saving…' : 'Save'}
        </button>
        {!isNew && (
          <button onClick={remove} disabled={busy}
            className="rounded-lg bg-red-600 px-4 font-semibold text-white disabled:opacity-50">Delete</button>
        )}
        <button onClick={() => navigate('/transfer')} className="rounded-lg border border-slate-300 px-4 font-medium">Cancel</button>
      </div>
    </div>
  )
}
