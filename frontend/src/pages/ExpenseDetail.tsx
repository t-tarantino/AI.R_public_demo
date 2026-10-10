import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CalendarDays, CreditCard, Pencil, Store, User } from 'lucide-react'
import { api } from '../api'
import { displayComment, formatDate, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'

interface Item {
  expense_item_id: number
  product_id: number | null
  customer_order_id: number | null
  expense_category_id: number
  description: string | null
  variant: string | null
  quantity: number
  unit_cost: string
  comment: string | null
}
interface Expense {
  expense_id: number
  paid_by_party_id: number
  paid_to_party_id: number
  date: string
  total_cost: string
  payment_method: string | null
  comment: string | null
  items: Item[]
}

export default function ExpenseDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const canEdit = useCanEdit()
  const [exp, setExp] = useState<Expense | null>(null)
  const [error, setError] = useState('')

  const parties = useOptions<{ party_id: number; name: string }>('/api/party')
  const cats = useOptions<{ expense_category_id: number; name: string }>('/api/expense_category')
  const products = useOptions<{ product_id: number; name: string }>('/api/product')
  const partyName = (i: number) => parties.find((p) => p.party_id === i)?.name ?? `#${i}`
  const catName = (i: number) => cats.find((c) => c.expense_category_id === i)?.name ?? `#${i}`
  const productName = (i: number | null) => (i ? products.find((p) => p.product_id === i)?.name : undefined)

  useEffect(() => {
    api.get<Expense>(`/api/expense/${id}`).then(setExp).catch((e) => setError(e.message))
  }, [id])

  if (error) return <p className="p-3 text-sm text-red-600">{error}</p>
  if (!exp) return <p className="p-6 text-center text-slate-400">Loading…</p>

  return (
    <div className="p-3">
      {/* 1. LINE ITEMS + TOTAL */}
      <div className="overflow-hidden rounded-xl bg-white shadow">
        <ul className="divide-y divide-slate-100">
          {exp.items.length === 0 && <li className="p-3 text-center text-sm text-slate-400">No lines.</li>}
          {exp.items.map((it) => (
            <li key={it.expense_item_id} className="p-3">
              <div className="flex items-baseline justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2 leading-snug">
                  <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-700">{catName(it.expense_category_id)}</span>
                  <span className="truncate font-medium">{productName(it.product_id) ?? it.description ?? '—'}</span>
                  {it.variant && <span className="shrink-0 rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-bold text-violet-700">digit {it.variant}</span>}
                </div>
                <div className="shrink-0 text-right text-sm">
                  <div className="text-slate-500">×{it.quantity} · {it.unit_cost}€</div>
                  <div className="font-semibold">{(Number(it.quantity) * Number(it.unit_cost)).toFixed(2)}€</div>
                </div>
              </div>
              {it.comment && <div className="mt-1 text-xs italic text-slate-400">{it.comment}</div>}
            </li>
          ))}
        </ul>
        <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-3 py-2">
          <span className="text-sm font-medium text-slate-500">Total</span>
          <span className="text-lg font-bold">{exp.total_cost}€</span>
        </div>
      </div>

      {/* 2. WHO / WHEN / HOW */}
      <div className="mt-3 space-y-2 rounded-xl bg-white p-3 shadow">
        <div className="flex items-center gap-2 text-sm">
          <Store size={16} className="shrink-0 text-slate-400" />
          <span className="font-medium">{partyName(exp.paid_to_party_id)}</span>
          <span className="text-slate-400">— supplier</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <User size={16} className="shrink-0 text-slate-400" />
          <span>Paid by {partyName(exp.paid_by_party_id)}</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <CalendarDays size={16} className="shrink-0 text-slate-400" />
          <span>{formatDate(exp.date)}</span>
        </div>
        {exp.payment_method && (
          <div className="flex items-center gap-2 text-sm">
            <CreditCard size={16} className="shrink-0 text-slate-400" />
            <span>{exp.payment_method}</span>
          </div>
        )}
        {displayComment(exp.comment, 'Expense') && <div className="text-xs italic text-slate-400">{displayComment(exp.comment, 'Expense')}</div>}
      </div>

      {/* 3. EDIT */}
      {canEdit && (
        <button onClick={() => navigate(`/expense/${id}/edit`)}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-violet-600 p-3 font-semibold text-white">
          <Pencil size={18} /> Edit
        </button>
      )}
    </div>
  )
}
