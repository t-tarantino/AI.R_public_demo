import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronRight, Store } from 'lucide-react'
import { api } from '../api'
import { formatDate, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'

interface Item {
  expense_category_id: number
  product_id: number | null
  description: string | null
  quantity: number
  unit_cost: string
}
interface Expense {
  expense_id: number
  paid_to_party_id: number
  date: string
  total_cost: string
  payment_method: string | null
  items: Item[]
}

export default function Expenses() {
  const canEdit = useCanEdit()
  const [rows, setRows] = useState<Expense[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const parties = useOptions<{ party_id: number; name: string }>('/api/party')
  const cats = useOptions<{ expense_category_id: number; name: string }>('/api/expense_category')
  const products = useOptions<{ product_id: number; name: string }>('/api/product')
  const partyName = (id: number) => parties.find((p) => p.party_id === id)?.name ?? `#${id}`
  const catName = (id: number) => cats.find((c) => c.expense_category_id === id)?.name ?? `#${id}`
  const productName = (id: number) => products.find((p) => p.product_id === id)?.name

  useEffect(() => {
    setLoading(true)
    api.get<Expense[]>('/api/expense')
      .then((data) => { setRows(data); setError(null) })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  // date -> payee -> expenses
  const groups = useMemo(() => {
    const byDate = new Map<string, Map<number, Expense[]>>()
    for (const e of rows) {
      const byPayee = byDate.get(e.date) ?? new Map<number, Expense[]>()
      const list = byPayee.get(e.paid_to_party_id) ?? []
      list.push(e)
      byPayee.set(e.paid_to_party_id, list)
      byDate.set(e.date, byPayee)
    }
    return [...byDate.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([date, byPayee]) => [
        date,
        [...byPayee.entries()].sort((a, b) => partyName(a[0]).localeCompare(partyName(b[0]))),
      ] as const)
  }, [rows, parties])

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">Expenses</h1>
        <div className="flex items-center gap-2">
          <Link to="/transfer" className="rounded-lg border border-violet-200 px-3 py-2 text-sm font-semibold text-violet-700">Transfers</Link>
          {canEdit && <Link to="/expense/new" className="rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white">+ Expense</Link>}
        </div>
      </div>

      {loading && <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">Loading…</p>}
      {!loading && error && (
        <p className="rounded-xl bg-white p-6 text-center text-red-600 shadow">Failed to load expenses: {error}</p>
      )}
      {!loading && !error && rows.length === 0 && (
        <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">No expenses.</p>
      )}

      <div className="space-y-4">
        {groups.map(([date, byPayee]) => (
          <section key={date} className="overflow-hidden rounded-xl bg-white shadow">
            <div className="bg-gradient-to-r from-violet-500 to-sky-400 px-3 py-2">
              <span className="rounded-full bg-white/25 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-white">
                {formatDate(date)}
              </span>
            </div>

            <div className="space-y-2 p-2">
              {byPayee.map(([payeeId, payeeExpenses]) => (
                <div key={payeeId} className="overflow-hidden rounded-lg border border-violet-100">
                  <div className="flex items-center gap-1 bg-violet-100 px-2.5 py-1.5">
                    <Store size={13} className="shrink-0 text-violet-500" />
                    <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs font-semibold text-violet-800">
                      {partyName(payeeId)}
                    </span>
                  </div>

                  <div className="space-y-1.5 bg-violet-50/40 p-1.5">
                    {payeeExpenses.map((e) => (
                      <div
                        key={e.expense_id}
                        onClick={() => navigate(`/expense/${e.expense_id}`)}
                        className="cursor-pointer rounded-md bg-white p-2 shadow-sm hover:bg-violet-50"
                      >
                        {e.items.length === 0 && <div className="px-1 text-xs text-slate-400">(no lines)</div>}
                        {e.items.map((it, i) => (
                          <div key={i} className="flex items-start gap-2 py-0.5">
                            <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-700">
                              {catName(it.expense_category_id)}
                            </span>
                            <div className="min-w-0 flex-1 text-sm font-medium">
                              {productName(it.product_id ?? -1) ?? it.description ?? '—'}
                            </div>
                            <span className="w-9 shrink-0 rounded-full bg-slate-100 py-0.5 text-center text-[11px] font-medium text-slate-600">×{it.quantity}</span>
                            <span className="w-14 shrink-0 rounded-full bg-slate-100 py-0.5 text-center text-[11px] font-medium text-slate-600">{it.unit_cost}€</span>
                          </div>
                        ))}
                        <div className="mt-1 flex items-center justify-end gap-2 border-t border-slate-100 pt-1">
                          {e.payment_method && <span className="text-[11px] text-slate-400">{e.payment_method}</span>}
                          <span className="text-sm font-semibold">{e.total_cost}€</span>
                          <ChevronRight size={15} className="text-slate-300" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
