import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { STATE_LABELS, useOptions } from '../lib/useOptions'

interface ColorLine { color_id: number | ''; color_percentage: string; color_surcharge: string }
interface NumberLine { required_item_id: number | ''; color_id: number | ''; digit: string }
interface ItemLine {
  composition_id: number | ''
  quantity: string
  unit_price: string
  discount: string
  colors: ColorLine[]
  numbers: NumberLine[]
}
interface Header {
  location_id: number | ''
  customer_party_id: number | ''
  state: string
  event_type: string
  celebrated_age: string
  celebrant_gender: string
  date: string
  total_price: string
  comment: string
}

const emptyHeader: Header = {
  location_id: '', customer_party_id: '', state: 'draft', event_type: '',
  celebrated_age: '', celebrant_gender: '', date: new Date().toISOString().slice(0, 10),
  total_price: '', comment: '',
}
const inputCls = 'mt-1 w-full rounded-lg border border-slate-300 bg-white p-3'

export default function OrderForm() {
  const { id } = useParams()
  const isNew = id === undefined
  const navigate = useNavigate()

  const [header, setHeader] = useState<Header>(emptyHeader)
  const [items, setItems] = useState<ItemLine[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // The order's state as last saved on the server — used to sequence the save.
  const [originalState, setOriginalState] = useState('draft')
  // existing orders — to warn about a possible duplicate (same location + date)
  const [existingOrders, setExistingOrders] = useState<{ customer_order_id: number; location_id: number; date: string; state: string }[]>([])

  const locations = useOptions<{ location_id: number; name: string; active: boolean }>('/api/location')
  const parties = useOptions<{ party_id: number; name: string; is_customer: boolean }>('/api/party')
  const comps = useOptions<{ composition_id: number; code: string; name: string; standard_price: string }>('/api/composition')
  const colors = useOptions<{ color_id: number; code: string; name: string; in_catalog: boolean }>('/api/color')
  const reqItems = useOptions<{ required_item_id: number; name: string; is_number: boolean }>('/api/required_item')
  const numberSizes = reqItems.filter((r) => r.is_number)
  const goldId = colors.find((c) => c.code === '088')?.color_id ?? ''
  const silverId = colors.find((c) => c.code === '089')?.color_id ?? ''

  useEffect(() => {
    if (isNew) return
    api.get<Record<string, unknown>>(`/api/order/${id}`).then((o) => {
      setOriginalState(o.state as string)
      setHeader({
        location_id: o.location_id as number,
        customer_party_id: (o.customer_party_id as number) ?? '',
        state: o.state as string,
        event_type: (o.event_type as string) ?? '',
        celebrated_age: o.celebrated_age === null ? '' : String(o.celebrated_age),
        celebrant_gender: (o.celebrant_gender as string) ?? '',
        date: o.date as string,
        total_price: String(o.total_price),
        comment: (o.comment as string) ?? '',
      })
      setItems((o.items as Record<string, unknown>[]).map((it) => ({
        composition_id: it.composition_id as number,
        quantity: String(it.quantity),
        unit_price: String(it.unit_price),
        discount: it.discount === null ? '' : String(it.discount),
        colors: (it.colors as Record<string, unknown>[]).map((c) => ({
          color_id: c.color_id as number,
          color_percentage: c.color_percentage === null ? '' : String(c.color_percentage),
          color_surcharge: (c.color_surcharge === null || c.color_surcharge === undefined || Number(c.color_surcharge) === 0)
            ? '' : String(c.color_surcharge),
        })),
        numbers: ((it.numbers as Record<string, unknown>[]) ?? []).map((n) => ({
          required_item_id: n.required_item_id as number,
          color_id: n.color_id as number,
          digit: String(n.digit),
        })),
      })))
    }).catch((e) => setError(e.message))
  }, [id, isNew])

  useEffect(() => {
    api.get<{ customer_order_id: number; location_id: number; date: string; state: string }[]>('/api/order')
      .then(setExistingOrders).catch(() => {})
  }, [])

  // Items are editable in any state except cancelled. Editing a completed order
  // rebuilds its stock consumption on the backend.
  const editable = header.state !== 'cancelled'

  // Soft checks (non-blocking): possible duplicate, and unit price off the list price.
  const duplicate = header.location_id !== '' && header.date
    ? existingOrders.find((o) => o.location_id === header.location_id && o.date === header.date
        && o.state !== 'cancelled' && o.customer_order_id !== Number(id))
    : undefined
  const listPriceOff = (it: ItemLine) => {
    const comp = comps.find((c) => c.composition_id === it.composition_id)
    if (!comp || it.unit_price === '') return null
    return Number(dec(it.unit_price)) !== Number(comp.standard_price) ? comp.standard_price : null
  }
  // The server rejects colour percentages that sum to >100; warn before saving so
  // the user sees it inline instead of a validation error on submit.
  const colorPctOver100 = (it: ItemLine): number | null => {
    const entered = it.colors.filter((c) => c.color_percentage !== '')
    if (entered.length === 0) return null
    const sum = entered.reduce((s, c) => s + num(c.color_percentage), 0)
    return sum > 100 ? sum : null
  }

  const OFF_CATALOG_SURCHARGE = 0.10  // off-catalog colours add 10% by default

  // Price maths: a line total is (unit × qty − discount) + colour surcharges;
  // the order total is the sum of the line totals (kept coherent by construction).
  // Italian mobile keyboards type a comma decimal separator; accept it everywhere.
  const dec = (s: string) => String(s).replace(',', '.')
  const num = (s: string) => { const n = Number(dec(s)); return Number.isFinite(n) ? n : 0 }
  const itemTotal = (it: ItemLine) => {
    const keep = 1 - num(it.discount) / 100
    const base = num(it.unit_price) * num(it.quantity) * keep
    const surcharge = it.colors.reduce((s, c) => s + num(c.color_surcharge) * keep, 0)
    return base + surcharge
  }
  const computedTotal = items.reduce((s, it) => s + (it.composition_id !== '' ? itemTotal(it) : 0), 0)

  // Keep the stored total in sync with the lines whenever there are items.
  useEffect(() => {
    if (items.length > 0) setHeader((h) => ({ ...h, total_price: computedTotal.toFixed(2) }))
  }, [computedTotal, items.length])

  // New orders default their customer to Riverside Hall.
  useEffect(() => {
    if (isNew && header.customer_party_id === '' && parties.length) {
      const tw = parties.find((p) => p.is_customer && p.name === 'Riverside Hall')
      if (tw) setHeader((h) => ({ ...h, customer_party_id: tw.party_id }))
    }
  }, [parties, isNew])

  const setItem = (i: number, patch: Partial<ItemLine>) =>
    setItems((its) => its.map((it, j) => (j === i ? { ...it, ...patch } : it)))
  // Off-catalog colour surcharges are 10% of the line base, so they must follow
  // the unit price / quantity / composition. Recompute them for off-catalog
  // colours whenever the line changes (in-catalog colours are left untouched).
  const recalcSurcharges = (it: ItemLine): ItemLine => ({
    ...it,
    colors: it.colors.map((c) => {
      const col = colors.find((x) => x.color_id === c.color_id)
      return col && col.in_catalog === false
        ? { ...c, color_surcharge: (num(it.unit_price) * num(it.quantity) * OFF_CATALOG_SURCHARGE).toFixed(2) }
        : c
    }),
  })
  const setItemRecalc = (i: number, patch: Partial<ItemLine>) =>
    setItems((its) => its.map((it, j) => (j === i ? recalcSurcharges({ ...it, ...patch }) : it)))
  const addItem = () =>
    setItems((its) => [...its, { composition_id: '', quantity: '1', unit_price: '', discount: '10', colors: [], numbers: [] }])
  const setColor = (i: number, k: number, patch: Partial<ColorLine>) =>
    setItems((its) => its.map((it, j) => j === i
      ? { ...it, colors: it.colors.map((c, m) => (m === k ? { ...c, ...patch } : c)) } : it))
  const setNumber = (i: number, k: number, patch: Partial<NumberLine>) =>
    setItems((its) => its.map((it, j) => j === i
      ? { ...it, numbers: it.numbers.map((n, m) => (m === k ? { ...n, ...patch } : n)) } : it))

  // Default the new number's size to the composition's number requirement.
  const addNumber = async (i: number) => {
    const it = items[i]
    let sizeDefault: number | '' = numberSizes[0]?.required_item_id ?? ''
    if (it.composition_id !== '') {
      try {
        const bom = await api.get<{ required_item_id: number }[]>(`/api/composition/${it.composition_id}/bom`)
        const hit = bom.find((b) => numberSizes.some((s) => s.required_item_id === b.required_item_id))
        if (hit) sizeDefault = hit.required_item_id
      } catch { /* keep the fallback default */ }
    }
    // Default number colour: silver, unless the item's balloon mix includes gold.
    const mixHasGold = goldId !== '' && it.colors.some((c) => c.color_id === goldId)
    const colorDefault = mixHasGold ? goldId : silverId
    setItem(i, { numbers: [...it.numbers, { required_item_id: sizeDefault, color_id: colorDefault, digit: '' }] })
  }

  const itemsPayload = () => items
    .filter((it) => it.composition_id !== '')
    .map((it) => ({
      composition_id: it.composition_id,
      quantity: Number(dec(it.quantity)),
      unit_price: dec(it.unit_price) || '0',
      discount: it.discount === '' ? null : dec(it.discount),
      colors: it.colors.filter((c) => c.color_id !== '').map((c) => ({
        color_id: c.color_id,
        color_percentage: c.color_percentage === '' ? null : dec(c.color_percentage),
        color_surcharge: c.color_surcharge === '' ? null : dec(c.color_surcharge),
      })),
      numbers: it.numbers.filter((n) => n.required_item_id !== '' && n.digit !== '').map((n) => ({
        required_item_id: n.required_item_id,
        color_id: n.color_id === '' ? null : n.color_id,
        digit: n.digit,
      })),
    }))

  const headerPayload = () => ({
    location_id: header.location_id,
    customer_party_id: header.customer_party_id === '' ? null : header.customer_party_id,
    state: header.state,
    event_type: header.event_type || null,
    celebrated_age: header.celebrated_age === '' ? null : Number(header.celebrated_age),
    celebrant_gender: header.celebrant_gender || null,
    date: header.date,
    total_price: dec(header.total_price) || '0',
    comment: header.comment || null,
  })

  const save = async () => {
    setBusy(true); setError('')
    try {
      if (isNew) {
        await api.post('/api/order', { ...headerPayload(), items: itemsPayload() })
      } else {
        // Two calls (there is no combined endpoint). Sequence them so a failure
        // can't leave the order half-updated and so completion consumption is
        // built from the NEW items:
        // - leaving 'cancelled': header first (items can't be edited while the
        //   order is still cancelled on the server);
        // - otherwise: items first, then the header, which may flip the order to
        //   'completed' — now from the items just saved (no stale double build).
        const leavingCancelled = originalState === 'cancelled' && header.state !== 'cancelled'
        if (leavingCancelled) {
          await api.patch(`/api/order/${id}`, headerPayload())
          if (editable) await api.put(`/api/order/${id}/items`, itemsPayload())
        } else {
          if (editable) await api.put(`/api/order/${id}/items`, itemsPayload())
          await api.patch(`/api/order/${id}`, headerPayload())
        }
      }
      navigate('/order')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!confirm('Delete this order? This cannot be undone.')) return
    setBusy(true); setError('')
    try {
      await api.delete(`/api/order/${id}`)
      navigate('/order')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setBusy(false) }
  }

  return (
    <div className="p-3">
      <h1 className="mb-4 text-xl font-bold">{isNew ? 'New order' : 'Order'}</h1>

      <div className="space-y-4 rounded-xl bg-white p-4 shadow">
        <label className="block"><span className="text-sm font-medium">Location *</span>
          <select className={inputCls} value={header.location_id}
            onChange={(e) => setHeader({ ...header, location_id: e.target.value === '' ? '' : Number(e.target.value) })}>
            <option value="">— choose —</option>
            {locations.filter((l) => l.active !== false || l.location_id === header.location_id)
              .map((l) => <option key={l.location_id} value={l.location_id}>{l.name}</option>)}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block"><span className="text-sm font-medium">Date *</span>
            <input type="date" className={inputCls} value={header.date}
              onChange={(e) => setHeader({ ...header, date: e.target.value })} />
          </label>
          <label className="block"><span className="text-sm font-medium">Status</span>
            <select className={inputCls} value={header.state}
              onChange={(e) => setHeader({ ...header, state: e.target.value })}>
              {['draft', 'confirmed', 'completed', 'cancelled'].map((s) =>
                <option key={s} value={s}>{STATE_LABELS[s]}</option>)}
            </select>
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block"><span className="text-sm font-medium">Event type</span>
            <input className={inputCls} value={header.event_type} placeholder="birthday…"
              onChange={(e) => setHeader({ ...header, event_type: e.target.value })} />
          </label>
          <label className="block"><span className="text-sm font-medium">Total price (€)</span>
            <input className={`${inputCls} ${items.length ? 'bg-slate-100 font-semibold text-slate-700' : ''}`}
              inputMode="decimal" readOnly={items.length > 0}
              value={items.length ? computedTotal.toFixed(2) : header.total_price}
              onChange={(e) => setHeader({ ...header, total_price: e.target.value })} />
            {items.length > 0 && <span className="mt-0.5 block text-[11px] text-slate-400">= sum of line subtotals (auto)</span>}
          </label>
        </div>
        <label className="block"><span className="text-sm font-medium">Customer</span>
          <select className={inputCls} value={header.customer_party_id}
            onChange={(e) => setHeader({ ...header, customer_party_id: e.target.value === '' ? '' : Number(e.target.value) })}>
            <option value="">— none —</option>
            {parties.filter((p) => p.is_customer).map((p) => <option key={p.party_id} value={p.party_id}>{p.name}</option>)}
          </select>
        </label>
      </div>

      {duplicate && (
        <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-700 ring-1 ring-amber-200">
          ⚠ Possible duplicate: an order already exists for this location on this date (#{duplicate.customer_order_id}).
        </p>
      )}

      <h2 className="mb-2 mt-5 font-semibold">Items</h2>
      <div className="space-y-3">
        {items.map((it, i) => {
          const comp = comps.find((c) => c.composition_id === it.composition_id)
          return (
            <div key={i} className="rounded-xl bg-white p-3 shadow">
              <div className="flex gap-2">
                <select
                  className="min-w-0 flex-1 rounded-lg border border-slate-300 p-2"
                  disabled={!editable}
                  value={it.composition_id}
                  onChange={(e) => {
                    const cid = e.target.value === '' ? '' : Number(e.target.value)
                    const c = comps.find((x) => x.composition_id === cid)
                    // Auto-sync the line price to the chosen composition's standard
                    // price — including when editing, so changing composition updates
                    // the price instead of keeping the old one. (Cleared = leave as is.)
                    // Recalc so off-catalog surcharges follow the new price.
                    setItemRecalc(i, { composition_id: cid, unit_price: cid === '' ? it.unit_price : (c?.standard_price ?? '') })
                  }}
                >
                  <option value="">— composition —</option>
                  {comps.map((c) => <option key={c.composition_id} value={c.composition_id}>{c.code} — {c.name}</option>)}
                </select>
                <button disabled={!editable} onClick={() => setItems((its) => its.filter((_, j) => j !== i))}
                  className="rounded-lg border border-red-200 px-2 text-red-600">✕</button>
              </div>
              <div className="mt-2 flex gap-2">
                <label className="flex-1 text-xs text-slate-500">Qty
                  <input className="mt-0.5 w-full rounded border border-slate-300 p-2" inputMode="numeric"
                    disabled={!editable} value={it.quantity} onChange={(e) => setItemRecalc(i, { quantity: e.target.value })} />
                </label>
                <label className="flex-1 text-xs text-slate-500">Unit price €
                  <input className="mt-0.5 w-full rounded border border-slate-300 p-2" inputMode="decimal"
                    disabled={!editable} value={it.unit_price} onChange={(e) => setItemRecalc(i, { unit_price: e.target.value })} />
                </label>
                <label className="flex-1 text-xs text-slate-500">Discount %
                  <input className="mt-0.5 w-full rounded border border-slate-300 p-2" inputMode="decimal"
                    disabled={!editable} value={it.discount} onChange={(e) => setItem(i, { discount: e.target.value })} />
                </label>
              </div>
              {/* colours */}
              <div className="mt-2 border-t border-slate-100 pt-2">
                {it.colors.map((c, k) => (
                  <div key={k} className="mt-1 flex items-center gap-2">
                    <select className="min-w-0 flex-1 rounded border border-slate-300 p-1.5 text-sm"
                      disabled={!editable} value={c.color_id}
                      onChange={(e) => {
                        const cid = e.target.value === '' ? '' : Number(e.target.value)
                        const col = colors.find((x) => x.color_id === cid)
                        const patch: Partial<ColorLine> = { color_id: cid }
                        // Off-catalog colour: auto-fill a 10% surcharge on the line base.
                        if (col && col.in_catalog === false) {
                          patch.color_surcharge = (num(it.unit_price) * num(it.quantity) * OFF_CATALOG_SURCHARGE).toFixed(2)
                        } else if (col) {
                          patch.color_surcharge = ''
                        }
                        setColor(i, k, patch)
                      }}>
                      <option value="">— color —</option>
                      {colors.map((col) => (
                        <option key={col.color_id} value={col.color_id}>
                          {col.code} {col.name}{col.in_catalog === false ? ' ⚠︎' : ''}
                        </option>
                      ))}
                    </select>
                    <input className="w-14 rounded border border-slate-300 p-1.5 text-right text-sm" inputMode="decimal"
                      placeholder="%" disabled={!editable} value={c.color_percentage}
                      onChange={(e) => setColor(i, k, { color_percentage: e.target.value })} />
                    <input className="w-16 rounded border border-slate-300 p-1.5 text-right text-sm" inputMode="decimal"
                      placeholder="+€" title="Surcharge € (off-catalog colour)"
                      disabled={!editable} value={c.color_surcharge}
                      onChange={(e) => setColor(i, k, { color_surcharge: e.target.value })} />
                    <button disabled={!editable}
                      onClick={() => setItem(i, { colors: it.colors.filter((_, m) => m !== k) })}
                      className="text-red-500">✕</button>
                  </div>
                ))}
                <button disabled={!editable}
                  onClick={() => setItem(i, { colors: [...it.colors, { color_id: '', color_percentage: '', color_surcharge: '' }] })}
                  className="mt-1 text-xs text-violet-600">+ color</button>
                {(() => {
                  // Under 100% is silently under-consumed on completion (>100 is
                  // caught separately below, as the server rejects it).
                  const entered = it.colors.map((c) => num(c.color_percentage)).filter((p) => p > 0)
                  const sum = entered.reduce((a, b) => a + b, 0)
                  return entered.length > 0 && sum > 0 && sum < 100 ? (
                    <div className="mt-1 text-[11px] text-amber-600">
                      ⚠︎ Colour percentages add up to {sum}%, not 100% — stock will be split on {sum}% only.
                    </div>
                  ) : null
                })()}
              </div>
              {/* numbers (foil digits: size + colour + digit) */}
              <div className="mt-2 border-t border-slate-100 pt-2">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Numbers</div>
                {it.numbers.map((n, k) => (
                  <div key={k} className="mt-1 flex items-center gap-2">
                    <input className="w-12 rounded border border-slate-300 p-1.5 text-center text-sm" inputMode="numeric"
                      maxLength={1} placeholder="#" disabled={!editable} value={n.digit}
                      onChange={(e) => setNumber(i, k, { digit: e.target.value.replace(/[^0-9]/g, '').slice(0, 1) })} />
                    <select className="w-24 shrink-0 rounded border border-slate-300 p-1.5 text-sm"
                      disabled={!editable} value={n.required_item_id}
                      onChange={(e) => setNumber(i, k, { required_item_id: e.target.value === '' ? '' : Number(e.target.value) })}>
                      <option value="">— size —</option>
                      {numberSizes.map((s) => <option key={s.required_item_id} value={s.required_item_id}>{s.name.replace('Palloncino numero ', '')}</option>)}
                    </select>
                    <select className="min-w-0 flex-1 rounded border border-slate-300 p-1.5 text-sm"
                      disabled={!editable} value={n.color_id}
                      onChange={(e) => setNumber(i, k, { color_id: e.target.value === '' ? '' : Number(e.target.value) })}>
                      <option value="">— color —</option>
                      {colors.map((col) => <option key={col.color_id} value={col.color_id}>{col.code} {col.name}</option>)}
                    </select>
                    <button disabled={!editable}
                      onClick={() => setItem(i, { numbers: it.numbers.filter((_, m) => m !== k) })}
                      className="text-red-500">✕</button>
                  </div>
                ))}
                <button disabled={!editable} onClick={() => addNumber(i)}
                  className="mt-1 text-xs text-violet-600">+ number</button>
              </div>
              <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2 text-xs">
                {comp ? <span className="text-slate-400">standard: {comp.standard_price}€</span> : <span />}
                <span className="font-semibold text-slate-600">Subtotal: €{itemTotal(it).toFixed(2)}</span>
              </div>
              {listPriceOff(it) && (
                <p className="mt-1 text-[11px] text-amber-600">⚠ price differs from list price ({listPriceOff(it)}€)</p>
              )}
              {colorPctOver100(it) && (
                <p className="mt-1 text-[11px] text-amber-600">⚠ colour percentages sum to {colorPctOver100(it)}% (over 100)</p>
              )}
            </div>
          )
        })}
      </div>
      {editable && (
        <button onClick={addItem} className="mt-3 w-full rounded-xl border-2 border-dashed border-slate-300 p-3 text-slate-500">
          + Add item
        </button>
      )}
      {!editable && <p className="mt-3 text-sm text-slate-500">Order {STATE_LABELS[header.state]}: items can't be edited.</p>}
      {editable && header.state === 'completed' && !isNew && (
        <p className="mt-3 text-sm text-amber-600">Editing a completed order will recompute its stock consumption.</p>
      )}

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-3">
        <button onClick={save} disabled={busy}
          className="flex-1 rounded-lg bg-violet-600 p-3 font-semibold text-white disabled:opacity-50">
          {busy ? 'Saving…' : 'Save'}
        </button>
        {!isNew && (
          <button onClick={remove} disabled={busy}
            className="rounded-lg bg-red-600 px-4 font-semibold text-white disabled:opacity-50">
            Delete
          </button>
        )}
        <button onClick={() => navigate('/order')} className="rounded-lg border border-slate-300 px-4 font-medium">
          Cancel
        </button>
      </div>
    </div>
  )
}
