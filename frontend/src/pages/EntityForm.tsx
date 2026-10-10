import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { entityByKey, type FieldDef } from '../entities'
import { useCanEdit } from '../lib/user'
import { BomSection } from './BomEditor'

type Row = Record<string, unknown>

export default function EntityForm() {
  const { entity, id } = useParams()
  const def = entityByKey(entity!)
  const isNew = id === undefined
  const navigate = useNavigate()
  const canEdit = useCanEdit()

  const [values, setValues] = useState<Row>({})
  const [fkOptions, setFkOptions] = useState<Record<string, Row[]>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!isNew) {
      api.get<Row>(`/api/${def.key}/${id}`).then(setValues).catch((e) => setError(e.message))
    } else {
      const defaults: Row = {}
      def.fields.forEach((f) => {
        if (f.default !== undefined) defaults[f.name] = f.default
        else if (f.type === 'bool') defaults[f.name] = f.name === 'active'
      })
      setValues(defaults)
    }
  }, [def, id, isNew])

  useEffect(() => {
    def.fields.filter((f) => f.type === 'fk').forEach((f) => {
      api.get<Row[]>(`/api/${f.fkEntity}`)
        .then((rows) => setFkOptions((m) => ({ ...m, [f.name]: rows })))
        .catch(() => {})
    })
  }, [def])

  const set = (name: string, value: unknown) => setValues((v) => ({ ...v, [name]: value }))

  const remove = async () => {
    if (!confirm(`Delete this ${def.titleOne.toLowerCase()}? This cannot be undone.`)) return
    setBusy(true); setError('')
    try {
      await api.delete(`/api/${def.key}/${id}`)
      navigate(`/e/${def.key}`)
    } catch (err) {
      // The server refuses (and explains) if the record is still in use.
      setError(err instanceof Error ? err.message : 'Delete error')
    } finally {
      setBusy(false)
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    // Empty strings -> null so optional fields clear correctly
    const payload: Row = {}
    def.fields.forEach((f) => {
      let value = values[f.name]
      if (value === '' || value === undefined) value = null
      payload[f.name] = value
    })
    try {
      if (isNew) {
        await api.post(`/api/${def.key}`, payload)
      } else {
        await api.patch(`/api/${def.key}/${id}`, payload)
      }
      navigate(`/e/${def.key}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save error')
    } finally {
      setBusy(false)
    }
  }

  const input = (f: FieldDef) => {
    const value = values[f.name]
    const base = 'mt-1 w-full rounded-lg border border-slate-300 bg-white p-3'
    switch (f.type) {
      case 'bool':
        return (
          <button
            type="button"
            onClick={() => set(f.name, !(value as boolean))}
            className={`mt-1 rounded-full px-4 py-2 text-sm font-semibold ${value ? 'bg-green-100 text-green-800' : 'bg-slate-200 text-slate-500'}`}
          >
            {value ? 'Yes' : 'No'}
          </button>
        )
      case 'textarea':
        return (
          <textarea
            className={base}
            rows={3}
            value={(value as string) ?? ''}
            onChange={(e) => set(f.name, e.target.value)}
          />
        )
      case 'fk': {
        const fkDef = entityByKey(f.fkEntity!)
        const options = fkOptions[f.name] ?? []
        return (
          <select
            className={base}
            value={value === null || value === undefined ? '' : String(value)}
            onChange={(e) => set(f.name, e.target.value === '' ? null : Number(e.target.value))}
          >
            <option value="">{f.required ? '— choose —' : '— none —'}</option>
            {options.map((o) => (
              <option key={String(o[fkDef.pk])} value={String(o[fkDef.pk])}>
                {f.fkLabel ? f.fkLabel(o) : String(o.name)}
              </option>
            ))}
          </select>
        )
      }
      case 'color': {
        const hex = typeof value === 'string' && value ? value : ''
        return (
          <div className="mt-1 flex items-center gap-3">
            <input
              type="color"
              value={hex || '#cccccc'}
              onChange={(e) => set(f.name, e.target.value)}
              className="h-11 w-16 cursor-pointer rounded-lg border border-slate-300 bg-white p-1"
            />
            <span className="font-mono text-sm text-slate-500">{hex || '— default —'}</span>
            {hex && (
              <button type="button" onClick={() => set(f.name, '')} className="text-xs text-slate-400 underline">
                rimuovi
              </button>
            )}
          </div>
        )
      }
      case 'decimal':
      case 'int':
        return (
          <input
            className={base}
            inputMode={f.type === 'int' ? 'numeric' : 'decimal'}
            value={value === null || value === undefined ? '' : String(value)}
            onChange={(e) => set(f.name, e.target.value)}
            placeholder={f.placeholder}
          />
        )
      default:
        return (
          <input
            className={base}
            value={(value as string) ?? ''}
            onChange={(e) => set(f.name, e.target.value)}
            placeholder={f.placeholder}
          />
        )
    }
  }

  return (
    <div className="p-3">
      <h1 className="mb-4 text-xl font-bold">
        {isNew ? `New ${def.titleOne}` : `Edit ${def.titleOne}`}
      </h1>
      <form onSubmit={submit} className="space-y-4 rounded-xl bg-white p-4 shadow">
        {def.fields.map((f) => (
          <label key={f.name} className="block">
            <span className="text-sm font-medium">
              {f.label}
              {f.required && <span className="text-red-500"> *</span>}
            </span>
            {input(f)}
            {f.help && <p className="mt-1 text-xs text-slate-400">{f.help}</p>}
          </label>
        ))}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex gap-3">
          {canEdit && (
            <button
              disabled={busy}
              className="flex-1 rounded-lg bg-violet-600 p-3 font-semibold text-white disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          )}
          <button
            type="button"
            onClick={() => navigate(`/e/${def.key}`)}
            className="flex-1 rounded-lg border border-slate-300 px-4 py-3 font-medium"
          >
            {canEdit ? 'Cancel' : 'Back'}
          </button>
        </div>
        {canEdit && def.hasDelete && !isNew && (
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="w-full rounded-lg border border-red-200 px-4 py-3 font-medium text-red-600 disabled:opacity-50"
          >
            Delete
          </button>
        )}
      </form>

      {/* Compositions edit their bill of materials on this same page. BOM needs a
          saved composition_id, so it appears only once the record exists. */}
      {def.key === 'composition' && !isNew && <BomSection compositionId={Number(id)} />}
    </div>
  )
}