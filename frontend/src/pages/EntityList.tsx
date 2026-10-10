import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { entityByKey } from '../entities'
import { useCanEdit } from '../lib/user'

type Row = Record<string, unknown>

export default function EntityList() {
  const { entity } = useParams()
  const def = entityByKey(entity!)
  const navigate = useNavigate()
  const canEdit = useCanEdit()
  const [rows, setRows] = useState<Row[]>([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  // FK id -> label maps for columns that reference other entities
  const [fkMaps, setFkMaps] = useState<Record<string, Record<number, string>>>({})

  useEffect(() => {
    const url = search ? `/api/${def.key}?search=${encodeURIComponent(search)}` : `/api/${def.key}`
    api.get<Row[]>(url).then(setRows).catch((e) => setError(e.message))
  }, [def.key, search])

  useEffect(() => {
    const fkFields = def.fields.filter((f) => f.type === 'fk')
    fkFields.forEach((f) => {
      api.get<Row[]>(`/api/${f.fkEntity}`).then((options) => {
        const map: Record<number, string> = {}
        const fkDef = entityByKey(f.fkEntity!)
        options.forEach((o) => {
          map[o[fkDef.pk] as number] = f.fkLabel ? f.fkLabel(o) : String(o.name ?? '')
        })
        setFkMaps((m) => ({ ...m, [f.name]: map }))
      }).catch(() => {})
    })
  }, [def])

  const cell = (row: Row, col: string) => {
    const value = row[col]
    if (value === null || value === undefined) return <span className="text-slate-300">—</span>
    if (fkMaps[col]) return fkMaps[col][value as number] ?? String(value)
    if (typeof value === 'boolean') return value ? '✓' : '✗'
    return String(value)
  }

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h1 className="text-xl font-bold">{def.title}</h1>
        {canEdit && (
          <Link
            to={`/e/${def.key}/new`}
            className="rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white"
          >
            + New
          </Link>
        )}
      </div>
      {def.description && (
        <p className="mb-3 rounded-xl bg-violet-50 p-3 text-sm text-slate-600 ring-1 ring-violet-100">
          {def.description}
        </p>
      )}
      {def.searchable && (
        <input
          className="mb-3 w-full rounded-lg border border-slate-300 bg-white p-3"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      )}
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
      <div className="overflow-hidden rounded-xl bg-white shadow">
        {rows.length === 0 && (
          <p className="p-6 text-center text-slate-400">No records.</p>
        )}
        <ul className="divide-y divide-slate-100">
          {rows.map((row) => {
            const id = row[def.pk] as number
            const inactive = def.hasActive && row.active === false
            return (
              <li
                key={id}
                onClick={() => navigate(`/e/${def.key}/${id}`)}
                className={`flex cursor-pointer items-center gap-3 p-3 hover:bg-violet-50 ${inactive ? 'opacity-40' : ''}`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-3">
                    {def.listColumns.map((c, i) => (
                      <span key={c.name} className={i === 0 ? 'font-semibold' : 'text-sm text-slate-500'}>
                        {cell(row, c.name)}
                      </span>
                    ))}
                  </div>
                </div>
                {inactive && <span className="shrink-0 text-xs">inactive</span>}
                <span className="shrink-0 text-slate-300">›</span>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}