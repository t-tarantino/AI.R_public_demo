import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { formatDate, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'

interface Line {
  required_item_id: number | ''
  color_id: number | ''
  variant: string
  quantity_change: string
}
const inputCls = 'mt-1 w-full rounded-lg border border-slate-300 bg-white p-3'

export default function InventoryForm() {
  const { id } = useParams()
  const isNew = id === undefined
  const isEdit = useLocation().pathname.endsWith('/edit')  // /inventory_update/:id/edit
  const navigate = useNavigate()
  const canEdit = useCanEdit()
  const [type, setType] = useState('recount')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [comment, setComment] = useState('')
  const [lines, setLines] = useState<Line[]>([{ required_item_id: '', color_id: '', variant: '', quantity_change: '' }])
  const [readonly, setReadonly] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const items = useOptions<{ required_item_id: number; name: string; dimension: string | null; used_color: boolean; is_number: boolean }>('/api/required_item')
  const colors = useOptions<{ color_id: number; code: string; name: string }>('/api/color')
  const mat = (i: number | '') => items.find((x) => x.required_item_id === i)
  const itemName = (i: number) => items.find((x) => x.required_item_id === i)?.name ?? `#${i}`
  const colorName = (i: number | null) => (i ? colors.find((c) => c.color_id === i)?.name : null)

  useEffect(() => {
    if (isNew) return
    api.get<Record<string, unknown>>(`/api/inventory_update/${id}`).then((data) => {
      if (!isEdit) { setReadonly(data); return }  // read-only view
      // --- edit mode: load the movement into the editable form ---
      const its = (data.items as Record<string, unknown>[]) ?? []
      setType(String(data.type))
      setDate(String(data.date).slice(0, 10))
      setComment((data.comment as string) ?? '')
      // A recount row already stores the counted ABSOLUTE, so edit it directly;
      // loss/gift store a signed delta, so show its magnitude.
      setLines(its.map((it) => ({
        required_item_id: it.required_item_id as number,
        color_id: (it.color_id as number | null) ?? '',
        variant: (it.variant as string | null) ?? '',
        quantity_change: String(data.type === 'recount'
          ? (it.quantity_change as number)
          : Math.abs(Number(it.quantity_change))),
      })))
    }).catch((e) => setError(e.message))
  }, [id, isNew, isEdit])

  const setLine = (i: number, patch: Partial<Line>) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))

  const save = async () => {
    setError('')
    const filled = lines.filter((l) => l.required_item_id !== '' && l.quantity_change !== '')
    if (filled.length === 0) { setError('Add at least one line.'); return }
    for (const l of filled) {
      const m = mat(l.required_item_id)
      const qty = Number(l.quantity_change)
      if (!Number.isFinite(qty)) { setError('Quantity must be a number.'); return }
      if (type === 'recount' ? qty < 0 : qty <= 0) {
        setError('Quantity must be positive.'); return
      }
      if (m?.is_number && l.variant === '') { setError('Digit (0–9) required for number balloons.'); return }
    }
    setBusy(true)
    const payload = {
      type, date, comment: comment || null,
      items: filled.map((l) => {
        const m = mat(l.required_item_id)
        return {
          required_item_id: l.required_item_id,
          color_id: m?.used_color && l.color_id !== '' ? l.color_id : null,
          variant: m?.is_number && l.variant !== '' ? l.variant : null,
          quantity_change: Number(l.quantity_change),
        }
      }),
    }
    try {
      if (isEdit) await api.patch(`/api/inventory_update/${id}`, payload)
      else await api.post('/api/inventory_update', payload)
      navigate('/inventory_update')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!confirm('Delete this stock update? This cannot be undone.')) return
    setBusy(true); setError('')
    try {
      await api.delete(`/api/inventory_update/${id}`)
      navigate('/inventory_update')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setBusy(false) }
  }

  // Read-only view of an existing movement (edit mode falls through to the form)
  if (!isNew && !isEdit) {
    const its = (readonly?.items as Record<string, unknown>[]) ?? []
    return (
      <div className="p-3">
        <h1 className="mb-1 text-xl font-bold">Stock update #{id}</h1>
        {readonly && <p className="mb-4 text-slate-500">{String(readonly.type)} · {formatDate(String(readonly.date))}</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <ul className="space-y-2">
          {its.map((l, i) => (
            <li key={i} className="flex items-center justify-between rounded-xl bg-white p-3 shadow">
              <div>
                <div className="font-semibold">{itemName(l.required_item_id as number)}</div>
                <div className="text-sm text-slate-500">
                  {[colorName(l.color_id as number | null), l.variant ? `digit ${l.variant}` : null].filter(Boolean).join(' · ') || '—'}
                </div>
              </div>
              {String(readonly?.type) === 'recount' ? (
                <span className="text-lg font-bold text-slate-700">={String(l.quantity_change)}</span>
              ) : (
                <span className={`text-lg font-bold ${(l.quantity_change as number) < 0 ? 'text-red-600' : 'text-green-700'}`}>
                  {(l.quantity_change as number) > 0 ? '+' : ''}{String(l.quantity_change)}
                </span>
              )}
            </li>
          ))}
        </ul>
        <div className="mt-4 flex gap-3">
          <button onClick={() => navigate('/inventory_update')} className="rounded-lg border border-slate-300 px-4 py-2 font-medium">Back</button>
          {canEdit && ['recount', 'loss', 'gift'].includes(String(readonly?.type)) && (
            <>
              <button onClick={() => navigate(`/inventory_update/${id}/edit`)}
                className="rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white">Edit</button>
              <button onClick={remove} disabled={busy}
                className="rounded-lg border border-red-200 px-4 py-2 font-medium text-red-600 disabled:opacity-50">Delete</button>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="p-3">
      <h1 className="mb-1 text-xl font-bold">{isEdit ? `Edit stock update #${id}` : 'New stock update'}</h1>
      <p className="mb-4 text-sm text-slate-500">
        {type === 'recount' && 'Recount: enter the actual counted quantity; stock is reconciled to it.'}
        {type === 'loss' && 'Loss: materials lost or damaged — enter how many.'}
        {type === 'gift' && 'Gift: materials received for free — enter how many.'}
        {' '}Purchases are recorded as an Expense; consumption is generated by orders.
      </p>
      <div className="mb-4">
        <span className={`inline-block rounded-full px-3 py-1 text-sm font-bold ${type === 'gift' ? 'bg-green-100 text-green-700' : type === 'loss' ? 'bg-red-100 text-red-700' : 'bg-slate-200 text-slate-700'}`}>
          {type === 'gift' ? '+ Adding stock' : type === 'loss' ? '− Removing stock' : '= Resetting stock to the counted value'}
        </span>
      </div>
      <div className="space-y-4 rounded-xl bg-white p-4 shadow">
        <div className="grid grid-cols-2 gap-3">
          <label className="block"><span className="text-sm font-medium">Type</span>
            <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
              <option value="recount">Recount (set actual qty)</option>
              <option value="loss">Loss (−)</option>
              <option value="gift">Gift (+)</option>
            </select>
          </label>
          <label className="block"><span className="text-sm font-medium">Date</span>
            <input type="date" className={inputCls} value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
        </div>
        <label className="block"><span className="text-sm font-medium">Notes</span>
          <input className={inputCls} value={comment} onChange={(e) => setComment(e.target.value)} />
        </label>
      </div>

      <h2 className="mb-2 mt-5 font-semibold">
        Lines <span className="font-normal text-slate-400">
          — {type === 'recount' ? 'counted quantity' : type === 'loss' ? 'quantity lost' : 'quantity received'}
        </span>
      </h2>
      <div className="space-y-3">
        {lines.map((l, i) => {
          const m = mat(l.required_item_id)
          return (
            <div key={i} className="rounded-xl bg-white p-3 shadow">
              <div className="flex gap-2">
                <select className="min-w-0 flex-1 rounded-lg border border-slate-300 p-2" value={l.required_item_id}
                  onChange={(e) => setLine(i, { required_item_id: e.target.value === '' ? '' : Number(e.target.value) })}>
                  <option value="">— material —</option>
                  {items.map((it) => <option key={it.required_item_id} value={it.required_item_id}>{it.name}{it.dimension ? ` (${it.dimension})` : ''}</option>)}
                </select>
                <button onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                  className="rounded-lg border border-red-200 px-2 text-red-600">✕</button>
              </div>
              <div className="mt-2 flex gap-2">
                {/* colour only for materials that come in colours */}
                {m?.used_color && (
                  <select className="flex-1 rounded-lg border border-slate-300 p-2 text-sm" value={l.color_id}
                    onChange={(e) => setLine(i, { color_id: e.target.value === '' ? '' : Number(e.target.value) })}>
                    <option value="">— color —</option>
                    {colors.map((c) => <option key={c.color_id} value={c.color_id}>{c.code} {c.name}</option>)}
                  </select>
                )}
                {/* digit only for number balloons, restricted to 0–9 */}
                {m?.is_number && (
                  <input className="w-20 rounded-lg border border-slate-300 p-2 text-center text-sm" inputMode="numeric"
                    maxLength={1} placeholder="digit" value={l.variant}
                    onChange={(e) => setLine(i, { variant: e.target.value.replace(/[^0-9]/g, '').slice(0, 1) })} />
                )}
                <input className="w-24 rounded-lg border border-slate-300 p-2 text-right" inputMode="numeric" placeholder="qty"
                  value={l.quantity_change} onChange={(e) => setLine(i, { quantity_change: e.target.value })} />
              </div>
            </div>
          )
        })}
      </div>
      <button onClick={() => setLines((ls) => [...ls, { required_item_id: '', color_id: '', variant: '', quantity_change: '' }])}
        className="mt-3 w-full rounded-xl border-2 border-dashed border-slate-300 p-3 text-slate-500">+ Add line</button>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex gap-3">
        <button onClick={save} disabled={busy} className="flex-1 rounded-lg bg-violet-600 p-3 font-semibold text-white disabled:opacity-50">
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button onClick={() => navigate('/inventory_update')} className="rounded-lg border border-slate-300 px-4 font-medium">Cancel</button>
      </div>
    </div>
  )
}
