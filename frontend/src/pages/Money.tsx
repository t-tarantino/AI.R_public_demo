import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowLeftRight, Receipt, TrendingUp } from 'lucide-react'
import { api } from '../api'
import { formatDateWithDay, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'
import PeriodFilter, { currentMonthRange } from '../components/PeriodFilter'

interface Summary { revenue: string; costs: string; profit: string }
interface Balance { party_id: number; name: string; code_nickname: string | null; amount: string }
interface OrderItem { composition_id: number; quantity: number }
interface Order {
  customer_order_id: number; date: string; state: string; total_price: string
  location_id: number; customer_party_id: number | null; items: OrderItem[]
}
interface ExpenseItem { product_id: number | null; description: string | null; quantity: number }
interface Expense {
  expense_id: number; date: string; paid_by_party_id: number; paid_to_party_id: number
  total_cost: string; items: ExpenseItem[]
}
interface Transfer { money_transfer_id: number; date: string; from_party_id: number; to_party_id: number; amount: string }

type Flow = {
  key: string
  date: string
  kind: 'revenue' | 'expense' | 'transfer'
  label: string
  badge?: string       // small pill next to the title (customer / who paid)
  detail: string
  amount: number
  to: string
}

// Money-flow filters (by kind).
const FLOW_TABS: { key: string; label: string; kinds: Flow['kind'][] }[] = [
  { key: 'all', label: 'All', kinds: ['revenue', 'expense', 'transfer'] },
  { key: 'revenue', label: 'Revenue', kinds: ['revenue'] },
  { key: 'expense', label: 'Expenses', kinds: ['expense'] },
  { key: 'transfer', label: 'Transfers', kinds: ['transfer'] },
]

export default function Money() {
  const canEdit = useCanEdit()
  const [[start, end], setRange] = useState<[string, string]>(currentMonthRange())
  const [summary, setSummary] = useState<Summary | null>(null)
  const [balances, setBalances] = useState<Balance[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [transfers, setTransfers] = useState<Transfer[]>([])
  const [flowKind, setFlowKind] = useState('all')
  const [error, setError] = useState('')
  const parties = useOptions<{ party_id: number; name: string }>('/api/party')
  const locations = useOptions<{ location_id: number; name: string }>('/api/location')
  const comps = useOptions<{ composition_id: number; name: string }>('/api/composition')
  const products = useOptions<{ product_id: number; name: string }>('/api/product')
  const pname = (id: number | null) => (id ? parties.find((p) => p.party_id === id)?.name ?? `#${id}` : '—')
  const locName = (id: number) => locations.find((l) => l.location_id === id)?.name ?? `#${id}`
  const compName = (id: number) => comps.find((c) => c.composition_id === id)?.name ?? `#${id}`
  const productName = (id: number | null) => (id ? products.find((p) => p.product_id === id)?.name : undefined)

  // "2× Arco Maxi · Backdrop · Centrotavola" — a one-line contents preview.
  const linePreview = (parts: { qty: number; label: string }[]) =>
    parts.map((p) => (p.qty > 1 ? `${p.qty}× ` : '') + p.label).join(' · ')

  useEffect(() => {
    api.get<Summary>(`/api/dashboard/summary?start=${start}&end=${end}`).then(setSummary).catch((e) => setError(e.message))
  }, [start, end])

  useEffect(() => {
    api.get<Balance[]>('/api/dashboard/balances').then(setBalances).catch(() => {})
    Promise.all([
      api.get<Order[]>('/api/order'),
      api.get<Expense[]>('/api/expense'),
      api.get<Transfer[]>('/api/money_transfer'),
    ]).then(([o, e, t]) => { setOrders(o); setExpenses(e); setTransfers(t) })
      .catch((err) => setError(err.message))
  }, [])

  const flows = useMemo(() => {
    const f: Flow[] = []
    for (const o of orders) {
      if (o.state !== 'completed') continue
      const preview = o.items.length
        ? linePreview(o.items.map((it) => ({ qty: it.quantity, label: compName(it.composition_id) })))
        : 'no items'
      f.push({ key: `o${o.customer_order_id}`, date: o.date, kind: 'revenue', label: locName(o.location_id),
        badge: o.customer_party_id ? pname(o.customer_party_id) : undefined,
        detail: preview, amount: Number(o.total_price), to: `/order/${o.customer_order_id}` })
    }
    for (const e of expenses) {
      const preview = linePreview(e.items.map((it) => ({ qty: it.quantity, label: productName(it.product_id) ?? it.description ?? '—' })))
      f.push({ key: `e${e.expense_id}`, date: e.date, kind: 'expense', label: pname(e.paid_to_party_id),
        badge: `Paid by ${pname(e.paid_by_party_id)}`,
        detail: preview || '—', amount: -Number(e.total_cost), to: `/expense/${e.expense_id}` })
    }
    for (const t of transfers) {
      f.push({ key: `t${t.money_transfer_id}`, date: t.date, kind: 'transfer', label: 'Transfer',
        detail: `${pname(t.from_party_id)} → ${pname(t.to_party_id)}`, amount: Number(t.amount), to: `/transfer/${t.money_transfer_id}` })
    }
    f.sort((a, b) => b.date.localeCompare(a.date))
    return f
  }, [orders, expenses, transfers, parties, locations, comps, products])

  const flowsByDate = useMemo(() => {
    const kinds = FLOW_TABS.find((t) => t.key === flowKind)?.kinds ?? []
    const m = new Map<string, Flow[]>()
    for (const fl of flows) {
      if (fl.date < start || fl.date > end) continue   // only the selected period
      if (!kinds.includes(fl.kind)) continue           // only the selected kind
      const l = m.get(fl.date) ?? []; l.push(fl); m.set(fl.date, l)
    }
    return [...m.entries()]
  }, [flows, start, end, flowKind])

  // Share of revenue, e.g. "72% of revenue" — shown under costs and profit.
  const pctOfRevenue = (value: string): string | undefined => {
    const rev = summary ? Number(summary.revenue) : 0
    if (!(rev > 0)) return undefined
    return `${Math.round((Number(value) / rev) * 100)}% of revenue`
  }

  const Metric = ({ label, value, accent, sub }: { label: string; value: string; accent?: string; sub?: string }) => (
    <div className="rounded-xl bg-white p-4 shadow">
      <div className="text-xs uppercase text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${accent ?? ''}`}>{value}€</div>
      {sub && <div className="mt-0.5 text-[11px] font-medium text-slate-400">{sub}</div>}
    </div>
  )

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">💰 Money</h1>
        <div className="flex items-center gap-2">
          {canEdit && <Link to="/transfer/new" className="rounded-lg border border-violet-200 px-3 py-2 text-sm font-semibold text-violet-700">+ Money Transfer</Link>}
          {canEdit && <Link to="/expense/new" className="rounded-lg bg-violet-600 px-3 py-2 text-sm font-semibold text-white">+ Expense</Link>}
        </div>
      </div>

      {error && <p className="mb-3 rounded-xl bg-red-50 p-3 text-center text-red-600 shadow ring-1 ring-red-200">{error}</p>}

      {/* period selector */}
      <PeriodFilter start={start} end={end} onChange={setRange} />
      {summary && (
        <div className="grid grid-cols-3 gap-2">
          <Metric label="Revenue" value={summary.revenue} />
          <Metric label="Costs" value={summary.costs} sub={pctOfRevenue(summary.costs)} />
          <Metric label="Profit" value={summary.profit} sub={pctOfRevenue(summary.profit)}
            accent={Number(summary.profit) < 0 ? 'text-red-600' : 'text-green-700'} />
        </div>
      )}


      {/* balances: who owes whom */}
      <h2 className="mb-2 mt-6 font-semibold">Balances</h2>
      {balances.length === 0 ? (
        <p className="rounded-xl bg-white p-4 text-sm text-slate-400 shadow">Everyone settled up.</p>
      ) : (
        <ul className="space-y-2">
          {balances.map((b) => {
            const amt = Number(b.amount)
            const weOwe = amt > 0
            return (
              <li key={b.party_id} className="flex items-center justify-between rounded-xl bg-white p-3 shadow">
                <span className="font-medium">{b.name}</span>
                <span className={`text-sm font-semibold ${weOwe ? 'text-amber-600' : 'text-green-700'}`}>
                  {weOwe ? `AI.R owes ${amt.toFixed(2)}€` : `owes AI.R ${Math.abs(amt).toFixed(2)}€`}
                </span>
              </li>
            )
          })}
        </ul>
      )}

      {/* unified money flows */}
      <h2 className="mb-2 mt-6 font-semibold">Money flows</h2>
      <div className="mb-3 flex flex-wrap gap-2">
        {FLOW_TABS.map((t) => (
          <button key={t.key} onClick={() => setFlowKind(t.key)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${flowKind === t.key ? 'bg-violet-600 text-white' : 'bg-white text-slate-600 shadow'}`}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="space-y-4">
        {flowsByDate.length === 0 && (
          <p className="rounded-xl bg-white p-4 text-sm text-slate-400 shadow">No money flows yet.</p>
        )}
        {flowsByDate.map(([date, dayFlows]) => (
          <section key={date} className="overflow-hidden rounded-xl bg-white shadow">
            <div className="bg-gradient-to-r from-violet-500 to-sky-400 px-3 py-2">
              <span className="rounded-full bg-white/25 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-white">
                {formatDateWithDay(date)}
              </span>
            </div>
            <FlowList flows={dayFlows} />
          </section>
        ))}
      </div>
    </div>
  )
}

function FlowList({ flows }: { flows: Flow[] }) {
  const navigate = useNavigate()
  const ICON = { revenue: TrendingUp, expense: Receipt, transfer: ArrowLeftRight }
  const TINT = { revenue: 'text-green-600', expense: 'text-red-600', transfer: 'text-slate-500' }
  return (
    <ul className="divide-y divide-slate-100">
      {flows.map((f) => {
        const Icon = ICON[f.kind]
        return (
          <li key={f.key} onClick={() => navigate(f.to)}
            className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-violet-50">
            <Icon size={18} className={`shrink-0 ${TINT[f.kind]}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="truncate text-sm font-medium">{f.label}</span>
                {f.badge && (
                  <span className="shrink-0 rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-semibold text-violet-700">
                    {f.badge}
                  </span>
                )}
              </div>
              <div className="truncate text-xs text-slate-500">{f.detail}</div>
            </div>
            <span className={`shrink-0 text-sm font-semibold ${f.kind === 'revenue' ? 'text-green-700' : f.kind === 'expense' ? 'text-red-600' : 'text-slate-600'}`}>
              {f.amount > 0 && f.kind !== 'transfer' ? '+' : ''}{f.amount < 0 ? '−' : ''}{Math.abs(f.amount).toFixed(2)}€
            </span>
          </li>
        )
      })}
    </ul>
  )
}
