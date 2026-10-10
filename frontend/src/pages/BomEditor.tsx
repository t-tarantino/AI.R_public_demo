import { useEffect, useState } from 'react'
import { api } from '../api'
import { useCanEdit } from '../lib/user'

interface BomLine {
  required_item_id: number | null
  quantity: string
  comment?: string | null
}

interface RequiredItem {
  required_item_id: number
  name: string
  dimension: string | null
  unit: string
}

// Embeddable BOM editor: shown inside the composition detail page (EntityForm),
// right below the other composition fields, so the whole item is edited in one
// place. It saves on its own (PUT /composition/:id/bom), independent of the
// composition's fields save.
export function BomSection({ compositionId }: { compositionId: number }) {
  const canEdit = useCanEdit()
  const [items, setItems] = useState<RequiredItem[]>([])
  const [lines, setLines] = useState<BomLine[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get<RequiredItem[]>('/api/required_item').then(setItems).catch(() => {})
    api.get<{ required_item_id: number; quantity: string; comment: string | null }[]>(
      `/api/composition/${compositionId}/bom`,
    ).then((bom) => {
      setLines(bom.map((l) => ({
        required_item_id: l.required_item_id,
        quantity: String(l.quantity),
        comment: l.comment,
      })))
    }).catch((e) => setError(e.message))
  }, [compositionId])

  const itemLabel = (itemId: number | null) => {
    const item = items.find((i) => i.required_item_id === itemId)
    return item ? `${item.name}${item.dimension ? ` (${item.dimension})` : ''}` : ''
  }
  const itemUnit = (itemId: number | null) =>
    items.find((i) => i.required_item_id === itemId)?.unit ?? ''

  const setLine = (index: number, patch: Partial<BomLine>) =>
    setLines((ls) => ls.map((l, i) => (i === index ? { ...l, ...patch } : l)))

  const save = async () => {
    setBusy(true)
    setError('')
    setSaved(false)
    try {
      const payload = lines
        .filter((l) => l.required_item_id !== null && l.quantity !== '')
        .map((l) => ({
          required_item_id: l.required_item_id,
          quantity: l.quantity,
          comment: l.comment || null,
        }))
      await api.put(`/api/composition/${compositionId}/bom`, payload)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 rounded-xl bg-white p-4 shadow">
      <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-violet-500">
        Bill of materials
      </h2>
      <div className="space-y-3">
        {lines.length === 0 && (
          <p className="text-sm text-slate-400">No materials yet.</p>
        )}
        {lines.map((line, i) => (
          <div key={i} className="flex items-center gap-2 rounded-lg bg-slate-50 p-2">
            <select
              className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white p-2"
              disabled={!canEdit}
              value={line.required_item_id === null ? '' : String(line.required_item_id)}
              onChange={(e) =>
                setLine(i, { required_item_id: e.target.value === '' ? null : Number(e.target.value) })}
            >
              <option value="">— material —</option>
              {items.map((item) => (
                <option key={item.required_item_id} value={String(item.required_item_id)}>
                  {itemLabel(item.required_item_id)}
                </option>
              ))}
            </select>
            <input
              className="w-20 rounded-lg border border-slate-300 p-2 text-right"
              inputMode="decimal"
              disabled={!canEdit}
              value={line.quantity}
              onChange={(e) => setLine(i, { quantity: e.target.value })}
            />
            <span className="w-10 shrink-0 text-xs text-slate-400">{itemUnit(line.required_item_id)}</span>
            {canEdit && (
              <button
                type="button"
                onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                className="shrink-0 rounded-lg border border-red-200 px-2 py-1 text-red-600"
                aria-label="remove"
              >
                ✕
              </button>
            )}
          </div>
        ))}
      </div>
      {canEdit && (
        <button
          type="button"
          onClick={() => setLines((ls) => [...ls, { required_item_id: null, quantity: '' }])}
          className="mt-3 w-full rounded-xl border-2 border-dashed border-slate-300 p-2.5 text-sm text-slate-500"
        >
          + Add material
        </button>
      )}
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {canEdit && (
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="mt-3 w-full rounded-lg bg-violet-600 p-3 font-semibold text-white disabled:opacity-50"
        >
          {busy ? 'Saving…' : saved ? 'BOM saved ✓' : 'Save BOM'}
        </button>
      )}
    </div>
  )
}
