import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CalendarDays, MapPin, Pencil } from 'lucide-react'
import { api } from '../api'
import { STATE_COLOR, STATE_LABELS, displayComment, formatDate, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'

interface ColorLine { color_id: number; color_percentage: string | null }
interface NumberLine { required_item_id: number; color_id: number; digit: string; quantity: number }
interface Item {
  order_item_id: number
  composition_id: number
  quantity: number
  unit_price: string
  discount: string | null
  colors: ColorLine[]
  numbers: NumberLine[]
}
interface Order {
  customer_order_id: number
  location_id: number
  customer_party_id: number | null
  state: string
  event_type: string | null
  celebrated_age: number | null
  celebrant_gender: string | null
  date: string
  total_price: string
  comment: string | null
  items: Item[]
}

export default function OrderDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const canEdit = useCanEdit()
  const [order, setOrder] = useState<Order | null>(null)
  const [error, setError] = useState('')

  const locations = useOptions<{ location_id: number; name: string }>('/api/location')
  const comps = useOptions<{ composition_id: number; code: string; name: string }>('/api/composition')
  const colors = useOptions<{ color_id: number; code: string; name: string }>('/api/color')
  const reqItems = useOptions<{ required_item_id: number; name: string }>('/api/required_item')
  const parties = useOptions<{ party_id: number; name: string }>('/api/party')
  const numSize = (i: number) => (reqItems.find((r) => r.required_item_id === i)?.name ?? '').replace('Palloncino numero ', '')
  const locName = (i: number) => locations.find((l) => l.location_id === i)?.name ?? `#${i}`
  const compName = (i: number) => comps.find((c) => c.composition_id === i)?.name ?? `#${i}`
  const compCode = (i: number) => comps.find((c) => c.composition_id === i)?.code ?? '?'
  const colorName = (i: number) => colors.find((c) => c.color_id === i)?.name ?? `#${i}`
  const colorCode = (i: number) => colors.find((c) => c.color_id === i)?.code ?? ''
  const partyName = (i: number) => parties.find((p) => p.party_id === i)?.name ?? `#${i}`

  useEffect(() => {
    api.get<Order>(`/api/order/${id}`).then(setOrder).catch((e) => setError(e.message))
  }, [id])

  if (error) return <p className="p-3 text-sm text-red-600">{error}</p>
  if (!order) return <p className="p-6 text-center text-slate-400">Loading…</p>

  const eventBits = [
    order.event_type,
    order.celebrated_age !== null ? `${order.celebrated_age} y` : null,
    order.celebrant_gender,
  ].filter(Boolean).join(' · ')

  return (
    <div className="p-3">
      {/* 1. ORDER DETAILS — the most important, shown first */}
      <div className="overflow-hidden rounded-xl bg-white shadow">
        <ul className="divide-y divide-slate-100">
          {order.items.length === 0 && (
            <li className="p-3 text-center text-sm text-slate-400">No items.</li>
          )}
          {order.items.map((it) => (
            <li key={it.order_item_id} className="p-3">
              <div className="flex items-baseline justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2 font-semibold leading-snug">
                  <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] font-bold text-slate-700">{compCode(it.composition_id)}</span>
                  <span className="truncate">{compName(it.composition_id)}</span>
                  {it.quantity > 1 && <span className="shrink-0 text-slate-400">×{it.quantity}</span>}
                </div>
                <div className="shrink-0 text-sm text-slate-500">
                  {it.unit_price}€{it.discount ? ` −${it.discount}%` : ''}
                </div>
              </div>
              {it.colors.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {it.colors.map((c) => (
                    <span key={c.color_id} className="rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700">
                      <span className="font-semibold">{colorCode(c.color_id)}</span> {colorName(c.color_id)}
                      {c.color_percentage ? ` ${Number(c.color_percentage)}%` : ''}
                    </span>
                  ))}
                </div>
              )}
              {it.numbers.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {it.numbers.map((n, k) => (
                    <span key={k} className="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700">
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-violet-600 text-[10px] font-bold text-white">{n.digit}</span>
                      {colorName(n.color_id)} · {numSize(n.required_item_id)}
                      {n.quantity > 1 ? ` ×${n.quantity}` : ''}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
        <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-3 py-2">
          <span className="text-sm font-medium text-slate-500">Total</span>
          <span className="text-lg font-bold">{order.total_price}€</span>
        </div>
      </div>

      {/* 2-4. DATE, LOCATION, STATUS — secondary, compact */}
      <div className="mt-3 space-y-2 rounded-xl bg-white p-3 shadow">
        <div className="flex items-center gap-2 text-sm">
          <CalendarDays size={16} className="shrink-0 text-slate-400" />
          <span>{formatDate(order.date)}</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <MapPin size={16} className="shrink-0 text-slate-400" />
          <span>{locName(order.location_id)}</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATE_COLOR[order.state] ?? ''}`}>
            {STATE_LABELS[order.state] ?? order.state}
          </span>
          {order.customer_party_id && <span className="text-slate-500">· {partyName(order.customer_party_id)}</span>}
        </div>
        {eventBits && <div className="text-xs text-slate-400">{eventBits}</div>}
        {displayComment(order.comment) && (
          <div className="text-xs italic text-slate-400">{displayComment(order.comment)}</div>
        )}
      </div>

      {/* 5. EDIT */}
      {canEdit && (
        <button
          onClick={() => navigate(`/order/${id}/edit`)}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-violet-600 p-3 font-semibold text-white"
        >
          <Pencil size={18} /> Edit
        </button>
      )}
    </div>
  )
}
