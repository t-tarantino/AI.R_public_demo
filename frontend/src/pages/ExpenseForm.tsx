import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useOptions } from '../lib/useOptions'
import SearchSelect, { type SearchOption } from '../components/SearchSelect'

// Products picked in expenses are remembered locally so the ones you actually
// buy float to the top of the picker, instead of hunting the full SKU list.
const RECENT_KEY = 'recentProductIds'
const RECENT_MAX = 8
const loadRecent = (): number[] => {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') } catch { return [] }
}

interface ItemLine {
  expense_category_id: number | ''
  product_id: number | ''
  description: string
  variant: string          // digit for number-balloon purchases
  quantity: string
  unit_cost: string
}
interface Header {
  paid_by_party_id: number | ''
  paid_to_party_id: number | ''
  date: string
  total_cost: string
  payment_method: string
  comment: string
}

const emptyHeader: Header = {
  paid_by_party_id: '', paid_to_party_id: '', date: new Date().toISOString().slice(0, 10),
  total_cost: '', payment_method: '', comment: '',
}
const inputCls = 'mt-1 w-full rounded-lg border border-slate-300 bg-white p-3'

export default function ExpenseForm() {
  const { id } = useParams()
  const isNew = id === undefined
  const navigate = useNavigate()
  const [header, setHeader] = useState<Header>(emptyHeader)
  const [items, setItems] = useState<ItemLine[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [existingExpenses, setExistingExpenses] = useState<{ expense_id: number; paid_to_party_id: number; date: string }[]>([])

  const parties = useOptions<{ party_id: number; name: string; is_customer: boolean; is_supplier: boolean; is_worker: boolean }>('/api/party')
  const cats = useOptions<{ expense_category_id: number; name: string }>('/api/expense_category')
  const products = useOptions<{ product_id: number; name: string; required_item_id: number; default_price: string | number | null; active?: boolean; product_code?: string | null; is_first_choice?: boolean }>('/api/product')
  const [recent, setRecent] = useState<number[]>(loadRecent)
  const recordRecent = (pid: number) => setRecent((prev) => {
    const next = [pid, ...prev.filter((x) => x !== pid)].slice(0, RECENT_MAX)
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)) } catch { /* ignore */ }
    return next
  })
  const defaultPriceOf = (pid: number | '') => {
    const dp = products.find((p) => p.product_id === pid)?.default_price
    return dp === null || dp === undefined || dp === '' ? null : Number(dp)
  }
  const reqItems = useOptions<{ required_item_id: number; is_number: boolean }>('/api/required_item')
  const numberReqIds = new Set(reqItems.filter((r) => r.is_number).map((r) => r.required_item_id))
  const isNumberProduct = (pid: number | '') => {
    const p = products.find((x) => x.product_id === pid)
    return p ? numberReqIds.has(p.required_item_id) : false
  }

  // Options for the searchable product picker: hide retired SKUs (but keep any
  // already chosen on a line, so editing an old expense still shows its product),
  // put recently-used first, then first-choice, then alphabetical. The digit of a
  // number balloon is NOT a separate product — it is picked per line below.
  const productOptions = useMemo<SearchOption[]>(() => {
    const chosen = new Set(items.map((it) => it.product_id).filter((v): v is number => v !== ''))
    const visible = products.filter((p) => p.active !== false || chosen.has(p.product_id))
    const toOpt = (p: typeof products[number], group: string): SearchOption => ({
      value: p.product_id, label: p.name, keywords: p.product_code ?? '',
      badge: p.is_first_choice ? '⭐' : undefined, group,
    })
    const recentHits = recent
      .map((id) => visible.find((p) => p.product_id === id))
      .filter((p): p is typeof products[number] => Boolean(p))
    const recentSet = new Set(recentHits.map((p) => p.product_id))
    const rest = visible.filter((p) => !recentSet.has(p.product_id))
      .sort((a, b) => Number(Boolean(b.is_first_choice)) - Number(Boolean(a.is_first_choice))
        || a.name.localeCompare(b.name))
    return [
      ...recentHits.map((p) => toOpt(p, 'Recent')),
      ...rest.map((p) => toOpt(p, 'All products')),
    ]
  }, [products, items, recent])

  useEffect(() => {
    if (isNew) return
    api.get<Record<string, unknown>>(`/api/expense/${id}`).then((e) => {
      setHeader({
        paid_by_party_id: e.paid_by_party_id as number,
        paid_to_party_id: e.paid_to_party_id as number,
        date: e.date as string,
        total_cost: String(e.total_cost),
        payment_method: (e.payment_method as string) ?? '',
        comment: (e.comment as string) ?? '',
      })
      setItems((e.items as Record<string, unknown>[]).map((it) => ({
        expense_category_id: it.expense_category_id as number,
        product_id: (it.product_id as number) ?? '',
        description: (it.description as string) ?? '',
        variant: (it.variant as string) ?? '',
        quantity: String(it.quantity),
        unit_cost: String(it.unit_cost),
      })))
    }).catch((e) => setError(e.message))
  }, [id, isNew])

  useEffect(() => {
    api.get<{ expense_id: number; paid_to_party_id: number; date: string }[]>('/api/expense')
      .then(setExistingExpenses).catch(() => {})
  }, [])

  const setItem = (i: number, patch: Partial<ItemLine>) =>
    setItems((its) => its.map((it, j) => (j === i ? { ...it, ...patch } : it)))

  // --- soft checks -----------------------------------------------------------
  const money = (s: string) => { const n = Number(String(s).replace(',', '.')); return Number.isFinite(n) ? n : 0 }
  const sumLines = items.filter((it) => it.expense_category_id !== '')
    .reduce((s, it) => s + money(it.quantity) * money(it.unit_cost), 0)
  const totalMismatch = header.total_cost !== '' && Math.abs(money(header.total_cost) - sumLines) > 0.005
  const samePayer = header.paid_by_party_id !== '' && header.paid_by_party_id === header.paid_to_party_id
  const dupExpense = header.paid_to_party_id !== '' && header.date
    ? existingExpenses.find((e) => e.paid_to_party_id === header.paid_to_party_id && e.date === header.date
        && e.expense_id !== Number(id))
    : undefined

  const itemsPayload = () => items.filter((it) => it.expense_category_id !== '').map((it) => ({
    expense_category_id: it.expense_category_id,
    product_id: it.product_id === '' ? null : it.product_id,
    description: it.description || null,
    variant: isNumberProduct(it.product_id) && it.variant !== '' ? it.variant : null,
    quantity: Number(String(it.quantity).replace(',', '.')),
    unit_cost: it.unit_cost.replace(',', '.') || '0',   // accept comma decimals (IT mobile)
  }))

  const save = async () => {
    setError('')
    if (samePayer) { setError('"Paid by" and "Paid to" must be different parties.'); return }
    setBusy(true)
    const head = {
      paid_by_party_id: header.paid_by_party_id,
      paid_to_party_id: header.paid_to_party_id,
      date: header.date,
      total_cost: header.total_cost === '' ? null : header.total_cost.replace(',', '.'),
      payment_method: header.payment_method || null,
      comment: header.comment || null,
    }
    try {
      if (isNew) {
        await api.post('/api/expense', { ...head, items: itemsPayload() })
      } else {
        // Save the lines first, then the header: if the second call fails the
        // header (date / parties / total) is left untouched rather than updated
        // against stale lines. The line save also rebuilds the stock refill.
        await api.put(`/api/expense/${id}/items`, itemsPayload())
        await api.patch(`/api/expense/${id}`, head)
      }
      navigate('/expense')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!confirm('Delete this expense? This cannot be undone.')) return
    setBusy(true); setError('')
    try {
      await api.delete(`/api/expense/${id}`)
      navigate('/expense')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setBusy(false) }
  }

  return (
    <div className="p-3">
      <h1 className="mb-4 text-xl font-bold">{isNew ? 'New expense' : 'Expense'}</h1>
      <div className="space-y-4 rounded-xl bg-white p-4 shadow">
        <label className="block"><span className="text-sm font-medium">Paid by *</span>
          <select className={inputCls} value={header.paid_by_party_id}
            onChange={(e) => setHeader({ ...header, paid_by_party_id: e.target.value === '' ? '' : Number(e.target.value) })}>
            <option value="">— choose —</option>
            {/* who fronts a business cost: workers/partners and customers (e.g. Riverside Hall advances payments) */}
            {parties.filter((p) => p.is_worker || p.is_customer || p.party_id === header.paid_by_party_id)
              .map((p) => <option key={p.party_id} value={p.party_id}>{p.name}</option>)}
          </select>
        </label>
        <label className="block"><span className="text-sm font-medium">Paid to *</span>
          <select className={inputCls} value={header.paid_to_party_id}
            onChange={(e) => setHeader({ ...header, paid_to_party_id: e.target.value === '' ? '' : Number(e.target.value) })}>
            <option value="">— choose —</option>
            {/* who receives the money: suppliers or workers */}
            {parties.filter((p) => p.is_supplier || p.is_worker || p.party_id === header.paid_to_party_id)
              .map((p) => <option key={p.party_id} value={p.party_id}>{p.name}</option>)}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block"><span className="text-sm font-medium">Date *</span>
            <input type="date" className={inputCls} value={header.date}
              onChange={(e) => setHeader({ ...header, date: e.target.value })} />
          </label>
          <label className="block"><span className="text-sm font-medium">Total € (auto if empty)</span>
            <input className={inputCls} inputMode="decimal" value={header.total_cost}
              onChange={(e) => setHeader({ ...header, total_cost: e.target.value })} />
          </label>
        </div>
        <label className="block"><span className="text-sm font-medium">Payment method</span>
          <input className={inputCls} value={header.payment_method} placeholder="card / cash…"
            onChange={(e) => setHeader({ ...header, payment_method: e.target.value })} />
        </label>
      </div>

      {/* soft checks */}
      {samePayer && <p className="mt-3 text-sm text-red-600">⚠ "Paid by" and "Paid to" must be different.</p>}
      {dupExpense && (
        <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-700 ring-1 ring-amber-200">
          ⚠ Possible duplicate: an expense to this supplier already exists on this date (#{dupExpense.expense_id}).
        </p>
      )}
      {totalMismatch && (
        <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-700 ring-1 ring-amber-200">
          ⚠ The entered total ({money(header.total_cost).toFixed(2)}€) differs from the sum of lines ({sumLines.toFixed(2)}€).
        </p>
      )}

      <h2 className="mb-2 mt-5 font-semibold">Lines</h2>
      <div className="space-y-3">
        {items.map((it, i) => (
          <div key={i} className="rounded-xl bg-white p-3 shadow">
            <div className="flex gap-2">
              <select className="min-w-0 flex-1 rounded-lg border border-slate-300 p-2" value={it.expense_category_id}
                onChange={(e) => setItem(i, { expense_category_id: e.target.value === '' ? '' : Number(e.target.value) })}>
                <option value="">— category —</option>
                {cats.map((c) => <option key={c.expense_category_id} value={c.expense_category_id}>{c.name}</option>)}
              </select>
              <button onClick={() => setItems((its) => its.filter((_, j) => j !== i))}
                className="rounded-lg border border-red-200 px-2 text-red-600">✕</button>
            </div>
            <SearchSelect className="mt-2" value={it.product_id} options={productOptions}
              placeholder="— product (optional) —"
              onChange={(pid) => {
                const dp = defaultPriceOf(pid)
                // Pre-fill the cost from the product's default (speeds up entry); the
                // user can still override it and will get a mismatch warning below.
                setItem(i, dp !== null ? { product_id: pid, unit_cost: String(dp) } : { product_id: pid })
                if (pid !== '') recordRecent(pid)
              }} />
            <input className="mt-2 w-full rounded-lg border border-slate-300 p-2" placeholder="Description"
              value={it.description} onChange={(e) => setItem(i, { description: e.target.value })} />
            {isNumberProduct(it.product_id) && (
              <label className="mt-2 block text-xs text-slate-500">Digit (number balloons)
                <input className="mt-0.5 w-20 rounded border border-slate-300 p-2 text-center" inputMode="numeric"
                  maxLength={1} placeholder="#" value={it.variant}
                  onChange={(e) => setItem(i, { variant: e.target.value.replace(/[^0-9]/g, '').slice(0, 1) })} />
              </label>
            )}
            <div className="mt-2 flex gap-2">
              <label className="flex-1 text-xs text-slate-500">Qty
                <input className="mt-0.5 w-full rounded border border-slate-300 p-2" inputMode="numeric"
                  value={it.quantity} onChange={(e) => setItem(i, { quantity: e.target.value })} />
              </label>
              <label className="flex-1 text-xs text-slate-500">Unit cost €
                <input className="mt-0.5 w-full rounded border border-slate-300 p-2" inputMode="decimal"
                  value={it.unit_cost} onChange={(e) => setItem(i, { unit_cost: e.target.value })} />
              </label>
            </div>
            {defaultPriceOf(it.product_id) !== null && it.unit_cost !== ''
              && Math.abs(money(it.unit_cost) - defaultPriceOf(it.product_id)!) > 0.005 && (
              <p className="mt-1 text-xs text-amber-700">
                ⚠ Unit cost differs from the product default (€{defaultPriceOf(it.product_id)!.toFixed(2)}).
              </p>
            )}
          </div>
        ))}
      </div>
      <button onClick={() => setItems((its) => [...its, { expense_category_id: '', product_id: '', description: '', variant: '', quantity: '1', unit_cost: '' }])}
        className="mt-3 w-full rounded-xl border-2 border-dashed border-slate-300 p-3 text-slate-500">
        + Add line
      </button>

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
        <button onClick={() => navigate('/expense')} className="rounded-lg border border-slate-300 px-4 font-medium">Cancel</button>
      </div>
    </div>
  )
}
