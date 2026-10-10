import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronRight, MapPin, MessageSquare } from 'lucide-react'
import { api } from '../api'
import { STATE_COLOR, STATE_LABELS, formatDateWithDay, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'
import PeriodFilter, { currentMonthRange } from '../components/PeriodFilter'

interface ColorLine { color_id: number; color_percentage: string | null }
interface NumberLine { required_item_id: number; color_id: number; digit: string; quantity: number }
interface Item {
  composition_id: number
  quantity: number
  unit_price: string
  colors: ColorLine[]
  numbers: NumberLine[]
}
interface Order {
  customer_order_id: number
  location_id: number
  date: string
  state: string
  total_price: string
  comment: string | null
  items: Item[]
}

// Split an order comment into provenance (AI.Richie vs by hand) and the real
// free-text comment, if any. Provenance/import markers ([richie]/[import]/
// [registro]) are NOT real comments, so they don't trigger the ⚠️ note.
function parseOrderComment(raw: string | null): { byRichie: boolean; text: string | null } {
  if (!raw) return { byRichie: false, text: null }
  const byRichie = /\[richie(?::[^\]]*)?\]/i.test(raw)
  if (/^\s*\[(import|registro)/i.test(raw)) return { byRichie, text: null }
  const text = raw.replace(/\s*\[richie(?::[^\]]*)?\]\s*/gi, ' ').trim()
  return { byRichie, text: text || null }
}

export default function Orders() {
  const canEdit = useCanEdit()
  const [orders, setOrders] = useState<Order[]>([])
  const [[start, end], setRange] = useState<[string, string]>(currentMonthRange())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const locations = useOptions<{ location_id: number; name: string }>('/api/location')
  const comps = useOptions<{ composition_id: number; code: string; name: string; comment?: string | null }>('/api/composition')
  const colors = useOptions<{ color_id: number; code: string; name: string }>('/api/color')
  const reqItems = useOptions<{ required_item_id: number; name: string }>('/api/required_item')
  const locName = (id: number) => locations.find((l) => l.location_id === id)?.name ?? `#${id}`
  const comp = (id: number) => comps.find((c) => c.composition_id === id)
  const color = (id: number) => colors.find((c) => c.color_id === id)
  const numSize = (id: number) => (reqItems.find((r) => r.required_item_id === id)?.name ?? '').replace('Palloncino numero ', '')
  // Combo contents live only as free text in the composition comment
  // ("Contiene: A + B. In omaggio: Nx Z."). Surface a compact form for combos:
  // "(A, B, Nx Z omaggio)".
  const comboInfo = (id: number) => {
    const c = comp(id)?.comment
    if (!c || !/^\s*contiene/i.test(c)) return null
    const parts: string[] = []
    const contains = c.match(/contiene:\s*([^.]*)/i)
    if (contains) parts.push(...contains[1].split('+').map((s) => s.trim()).filter(Boolean))
    const gift = c.match(/omaggio:\s*([^.]*)/i)
    if (gift && gift[1].trim()) parts.push(`${gift[1].trim()} omaggio`)
    return parts.length ? `(${parts.join(', ')})` : c
  }

  // Group an order's items by their EXACT colour set (same color_ids + %), in
  // first-appearance order. Lets same-coloured compositions sit together with
  // their shared colours printed only once.
  const colorGroups = (items: Item[]) => {
    const order: string[] = []
    const byKey = new Map<string, { colors: ColorLine[]; items: Item[] }>()
    for (const it of items) {
      const key = it.colors.map((c) => `${c.color_id}:${c.color_percentage ?? ''}`).sort().join('|')
      if (!byKey.has(key)) { byKey.set(key, { colors: it.colors, items: [] }); order.push(key) }
      byKey.get(key)!.items.push(it)
    }
    return order.map((k) => byKey.get(k)!)
  }

  useEffect(() => {
    setLoading(true)
    api.get<Order[]>('/api/order')
      .then((data) => { setOrders(data); setError(null) })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  // Orders whose date falls inside the selected period.
  const visibleOrders = useMemo(
    () => orders.filter((o) => o.date >= start && o.date <= end),
    [orders, start, end],
  )

  // Today (local ISO, no UTC day-shift) — used to spot the "next available day".
  const todayIso = useMemo(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }, [])

  // Group: date -> location -> orders. Dates newest first, locations A→Z.
  const groups = useMemo(() => {
    const byDate = new Map<string, Map<number, Order[]>>()
    for (const o of visibleOrders) {
      const byLoc = byDate.get(o.date) ?? new Map<number, Order[]>()
      const list = byLoc.get(o.location_id) ?? []
      list.push(o)
      byLoc.set(o.location_id, list)
      byDate.set(o.date, byLoc)
    }
    return [...byDate.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([date, byLoc]) => [
        date,
        [...byLoc.entries()].sort((a, b) => locName(a[0]).localeCompare(locName(b[0]))),
      ] as const)
  }, [visibleOrders, locations])

  // The next NOT-completed order: the earliest date (today or later) that still
  // has an order to work on (not completed, not cancelled). Days whose orders are
  // all done are skipped. That date's section is highlighted in amber below.
  const highlightDate = useMemo(() => {
    const dates = visibleOrders
      .filter((o) => o.date >= todayIso && o.state !== 'completed' && o.state !== 'cancelled')
      .map((o) => o.date)
    return dates.length ? dates.reduce((a, b) => (a < b ? a : b)) : null
  }, [visibleOrders, todayIso])

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">🎉 Orders</h1>
        {canEdit && <Link to="/order/new" className="rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white">+ Order</Link>}
      </div>

      <PeriodFilter start={start} end={end} onChange={setRange} />

      {loading && <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">Loading…</p>}
      {!loading && error && (
        <p className="rounded-xl bg-white p-6 text-center text-red-600 shadow">Failed to load orders: {error}</p>
      )}
      {!loading && !error && visibleOrders.length === 0 && (
        <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">No orders in this period.</p>
      )}

      <div className="space-y-4">
        {groups.map(([date, byLoc]) => {
          // `hot` = the next available day: rendered as a bigger, yellow, emoji
          // board; all other dates keep the compact violet style.
          const hot = date === highlightDate
          return (
          <section key={date} className={`overflow-hidden rounded-xl bg-white shadow ${hot ? 'ring-2 ring-amber-300' : ''}`}>
            {/* DATE band — dark→light yellow when hot, else violet→sky */}
            <div className={`flex items-center gap-1.5 px-3 py-2 ${hot ? 'bg-gradient-to-r from-amber-500 to-amber-200' : 'bg-gradient-to-r from-violet-500 to-sky-400'}`}>
              {hot && <span className="text-xl leading-none">📆</span>}
              <span className={`rounded-full bg-white/25 px-2.5 py-0.5 font-bold uppercase tracking-wide text-white ${hot ? 'text-sm' : 'text-xs'}`}>
                {formatDateWithDay(date)}{hot ? ' · Next orders' : ''}
              </span>
            </div>

            <div className="space-y-2 p-2">
              {byLoc.map(([locId, locOrders]) => (
                <div key={locId} className={`overflow-hidden rounded-lg border ${hot ? 'border-amber-200' : 'border-violet-100'}`}>
                  {/* LOCATION band */}
                  <div className={`flex items-center gap-1 px-2.5 py-1.5 ${hot ? 'bg-amber-100' : 'bg-violet-100'}`}>
                    {hot ? <span className="text-xl leading-none">📍</span> : <MapPin size={13} className="shrink-0 text-violet-500" />}
                    <span className={`rounded-full bg-white/70 px-2 py-0.5 font-semibold ${hot ? 'text-sm text-amber-800' : 'text-xs text-violet-800'}`}>
                      {locName(locId)}
                    </span>
                  </div>

                  <div className={`space-y-1.5 p-1.5 ${hot ? 'bg-amber-50/60' : 'bg-violet-50/40'}`}>
                    {locOrders.map((o) => (
                      <div
                        key={o.customer_order_id}
                        onClick={() => navigate(`/order/${o.customer_order_id}`)}
                        className={`cursor-pointer rounded-md bg-white p-2 shadow-sm ${hot ? 'hover:bg-amber-50' : 'hover:bg-violet-50'}`}
                      >
                        {o.items.length === 0 && <div className="px-1 text-xs text-slate-400">(no items)</div>}
                        {colorGroups(o.items).map((g, gi) => (
                          <div key={gi} className="py-0.5">
                            {g.items.map((it, i) => (
                              <div key={i}>
                                {/* line 1: code, name, quantity, price */}
                                <div className="flex items-center gap-2">
                                  {/* composition code — neutral bubble */}
                                  <span className={`shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono font-bold text-slate-700 ${hot ? 'text-sm' : 'text-[11px]'}`}>
                                    {comp(it.composition_id)?.code ?? '?'}
                                  </span>
                                  <span className={`min-w-0 flex-1 font-medium ${hot ? 'text-base' : 'text-sm'}`}>
                                    {comp(it.composition_id)?.name ?? `#${it.composition_id}`}
                                  </span>
                                  {/* quantity + price — right, aligned across rows */}
                                  <span className={`w-9 shrink-0 rounded-full bg-slate-100 py-0.5 text-center font-medium text-slate-600 ${hot ? 'text-sm' : 'text-[11px]'}`}>×{it.quantity}</span>
                                  <span className={`w-14 shrink-0 rounded-full bg-slate-100 py-0.5 text-center font-medium text-slate-600 ${hot ? 'text-sm' : 'text-[11px]'}`}>{it.unit_price}€</span>
                                </div>
                                {/* combo contents (free text from the composition comment) */}
                                {comboInfo(it.composition_id) && (
                                  <div className={`mt-0.5 pl-1 text-slate-500 ${hot ? 'text-sm' : 'text-[11px]'}`}>
                                    {comboInfo(it.composition_id)}
                                  </div>
                                )}
                              </div>
                            ))}
                            {/* shared colours — printed once, under all this group's compositions */}
                            {g.colors.length > 0 && (
                              <div className={`mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 ${hot ? 'text-sm' : 'text-[11px]'}`}>
                                {hot && <span className="text-xl leading-none">🎨</span>}
                                {g.colors.map((c) => (
                                  <span key={c.color_id} className="rounded-full bg-sky-50 px-2 py-0.5 font-medium text-sky-700">
                                    <span className="font-semibold">{color(c.color_id)?.code}</span> {color(c.color_id)?.name}
                                    {c.color_percentage ? ` ${Number(c.color_percentage)}%` : ''}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                        {/* numbers — collected at the very end of the order, after colours */}
                        {o.items.some((it) => it.numbers.length > 0) && (
                          <div className={`mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 ${hot ? 'text-sm' : 'text-[11px]'}`}>
                            {hot && <span className="text-xl leading-none">🔢</span>}
                            {o.items.flatMap((it) => it.numbers).map((n, k) => (
                              <span key={k} className="inline-flex items-center gap-1 rounded-full bg-violet-50 px-1.5 py-0.5 font-medium text-violet-700">
                                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-violet-600 text-[9px] font-bold text-white">{n.digit}</span>
                                {color(n.color_id)?.name}{numSize(n.required_item_id) ? ` · ${numSize(n.required_item_id)}` : ''}
                              </span>
                            ))}
                          </div>
                        )}
                        {parseOrderComment(o.comment).text && (
                          <div className={`mt-1 flex items-center gap-1 italic text-slate-500 ${hot ? 'text-sm' : 'text-[11px]'}`}>
                            {hot ? <span className="text-xl leading-none">⚠️</span> : <MessageSquare size={12} className="mt-0.5 shrink-0 text-slate-400" />}
                            <span>{parseOrderComment(o.comment).text}</span>
                          </div>
                        )}
                        <div className="mt-1 flex items-center justify-end gap-2 border-t border-slate-100 pt-1">
                          {parseOrderComment(o.comment).byRichie && (
                            <span className="mr-auto text-[10px] text-slate-400">written by AI.Richie</span>
                          )}
                          {/* A draft whose event day has already passed gets a light-red
                              badge (it should have been confirmed/completed by now). */}
                          <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${o.state === 'draft' && o.date < todayIso ? 'bg-red-100 text-red-700' : (STATE_COLOR[o.state] ?? '')}`}>{STATE_LABELS[o.state] ?? o.state}</span>
                          <span className={`flex items-center gap-1 font-semibold ${hot ? 'text-base' : 'text-sm'}`}>{hot && <span className="text-xl leading-none">💰</span>}{o.total_price}€</span>
                          <ChevronRight size={15} className="text-slate-300" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
          )
        })}
      </div>
    </div>
  )
}
