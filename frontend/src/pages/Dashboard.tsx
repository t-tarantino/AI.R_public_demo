import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { useOptions } from '../lib/useOptions'
import PeriodFilter, { currentMonthRange } from '../components/PeriodFilter'

interface Scalar { kind: string; current: number | null; pct_change: number | null }
interface SeriesPoint { key: string | number; label: string; value: number | null }
interface Opt { id: number; name: string }

// --- metrics: each declares the dimensions it can break down / filter by -----
interface MetricDef { key: string; label: string; kind: string; dims: string[] }
const METRICS: MetricDef[] = [
  { key: 'revenue', label: 'Revenue', kind: 'money', dims: ['composition', 'color', 'location', 'customer'] },
  { key: 'profit', label: 'Profit', kind: 'money', dims: [] },
  { key: 'costs', label: 'Costs', kind: 'money', dims: ['payee'] },
  { key: 'orders', label: 'Orders', kind: 'count', dims: ['location'] },
  { key: 'hours', label: 'Hours', kind: 'hours', dims: ['worker'] },
  { key: 'avg_order_value', label: 'Avg order', kind: 'money', dims: [] },
  { key: 'revenue_per_hour', label: 'Revenue/hour', kind: 'money', dims: [] },
  { key: 'profit_per_hour', label: 'Profit/hour', kind: 'money', dims: [] },
  { key: 'items_sold', label: 'Units sold', kind: 'count', dims: ['composition', 'location', 'customer'] },
  { key: 'material_used', label: 'Material used', kind: 'count', dims: ['color', 'material'] },
]
const M = (k: string) => METRICS.find((m) => m.key === k)!
const KPIS = ['revenue', 'profit', 'costs', 'hours', 'orders']
const DIM_LABEL: Record<string, string> = {
  time: 'Time', location: 'Location', customer: 'Customer', worker: 'Worker',
  payee: 'Supplier', composition: 'Composition', color: 'Colour', material: 'Material',
}
const SERIES_COLORS = ['#7c3aed', '#0ea5e9', '#f59e0b', '#10b981', '#ec4899', '#64748b']

const fmt = (kind: string, v: number | null | undefined) => {
  if (v === null || v === undefined) return '—'
  if (kind === 'count') return String(Math.round(v * 10) / 10)
  if (kind === 'hours') return `${v}h`
  return `${Number(v).toFixed(2)}€`
}
function granularityFor(start: string, end: string): 'day' | 'week' | 'month' {
  const days = (new Date(end).getTime() - new Date(start).getTime()) / 86400000 + 1
  if (days <= 31) return days <= 10 ? 'day' : 'week'
  return 'month'
}

export default function Analytics() {
  const [[start, end], setRange] = useState<[string, string]>(currentMonthRange())
  const [metrics, setMetrics] = useState<string[]>(['revenue'])
  const [breakdown, setBreakdown] = useState('time')            // 'total' | 'time' | dim
  const [filters, setFilters] = useState<Record<string, number[]>>({})

  const [kpis, setKpis] = useState<Record<string, Scalar>>({})
  const [totals, setTotals] = useState<Record<string, Scalar>>({})
  const [seriesByMetric, setSeriesByMetric] = useState<Record<string, SeriesPoint[]>>({})
  const [error, setError] = useState('')

  const locations = useOptions<{ location_id: number; name: string }>('/api/location')
  const parties = useOptions<{ party_id: number; name: string; is_worker: boolean; is_customer: boolean; is_supplier: boolean }>('/api/party')
  const comps = useOptions<{ composition_id: number; name: string }>('/api/composition')
  const colors = useOptions<{ color_id: number; name: string }>('/api/color')
  const reqItems = useOptions<{ required_item_id: number; name: string }>('/api/required_item')

  // Options for each filter/breakdown dimension.
  const dimOptions = (dim: string): Opt[] => {
    if (dim === 'location') return locations.map((l) => ({ id: l.location_id, name: l.name }))
    if (dim === 'worker') return parties.filter((p) => p.is_worker).map((p) => ({ id: p.party_id, name: p.name }))
    if (dim === 'customer') return parties.filter((p) => p.is_customer).map((p) => ({ id: p.party_id, name: p.name }))
    if (dim === 'payee') return parties.filter((p) => p.is_supplier).map((p) => ({ id: p.party_id, name: p.name }))
    if (dim === 'composition') return comps.map((c) => ({ id: c.composition_id, name: c.name }))
    if (dim === 'color') return colors.map((c) => ({ id: c.color_id, name: c.name }))
    if (dim === 'material') return reqItems.map((r) => ({ id: r.required_item_id, name: r.name }))
    return []
  }

  const selectedDefs = metrics.map(M)
  const breakdownDims = selectedDefs.length
    ? selectedDefs.reduce<string[]>((acc, d) => acc.filter((x) => d.dims.includes(x)), [...selectedDefs[0].dims])
    : []
  const filterDims = [...new Set(selectedDefs.flatMap((d) => d.dims))]
  const breakdownOptions = ['total', 'time', ...breakdownDims]

  const scopeQS = useMemo(() =>
    Object.entries(filters).flatMap(([dim, ids]) => ids.map((id) => `&scope_${dim}=${id}`)).join(''),
    [filters])

  // Keep breakdown valid as metrics change.
  useEffect(() => {
    if (!breakdownOptions.includes(breakdown)) setBreakdown('time')
  }, [metrics]) // eslint-disable-line react-hooks/exhaustive-deps

  // KPI strip.
  useEffect(() => {
    Promise.all(KPIS.map((m) =>
      api.get<Scalar>(`/api/metrics/${m}?start=${start}&end=${end}&compare=true`).then((r) => [m, r] as const)))
      .then((rows) => setKpis(Object.fromEntries(rows))).catch((e) => setError(e.message))
  }, [start, end])

  // Explorer: per-metric total (compare) + optional breakdown series.
  useEffect(() => {
    if (metrics.length === 0) { setTotals({}); setSeriesByMetric({}); return }
    Promise.all(metrics.map((m) =>
      api.get<Scalar>(`/api/metrics/${m}?start=${start}&end=${end}&compare=true${scopeQS}`).then((r) => [m, r] as const)))
      .then((rows) => setTotals(Object.fromEntries(rows))).catch((e) => setError(e.message))

    if (breakdown === 'total') { setSeriesByMetric({}); return }
    const gb = breakdown === 'time' ? granularityFor(start, end) : breakdown
    Promise.all(metrics.map((m) =>
      api.get<{ series: SeriesPoint[] }>(`/api/metrics/${m}?start=${start}&end=${end}&group_by=${gb}${scopeQS}`)
        .then((r) => [m, r.series] as const).catch(() => [m, []] as const)))
      .then((rows) => setSeriesByMetric(Object.fromEntries(rows)))
  }, [metrics, breakdown, start, end, scopeQS])

  // Merge each metric's series into chart rows keyed by the breakdown bucket.
  const rows = useMemo(() => {
    const map = new Map<string, Record<string, string | number | null>>()
    for (const m of metrics) {
      for (const pt of seriesByMetric[m] ?? []) {
        const k = String(pt.key)
        const row = map.get(k) ?? { __key: k, __label: pt.label }
        row[m] = pt.value
        map.set(k, row)
      }
    }
    const arr = [...map.values()]
    if (breakdown === 'time') arr.sort((a, b) => String(a.__key).localeCompare(String(b.__key)))
    else arr.sort((a, b) => (Number(b[metrics[0]] ?? 0)) - (Number(a[metrics[0]] ?? 0)))
    return arr
  }, [metrics, seriesByMetric, breakdown])

  const toggleMetric = (k: string) =>
    setMetrics((ms) => ms.includes(k) ? ms.filter((x) => x !== k) : [...ms, k])

  const Chip = ({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) => (
    <button onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-sm font-medium ${on ? 'bg-violet-600 text-white' : 'bg-white text-slate-600 shadow'}`}>
      {children}
    </button>
  )
  const selectCls = 'rounded-lg border border-slate-300 bg-white p-2 text-sm'

  // Filter for one dimension: a dropdown to add + removable chips.
  const DimFilter = ({ dim }: { dim: string }) => {
    const opts = dimOptions(dim)
    const sel = filters[dim] ?? []
    const set = (ids: number[]) => setFilters((f) => ({ ...f, [dim]: ids }))
    return (
      <div className="rounded-lg bg-white p-2 shadow-sm">
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{DIM_LABEL[dim]}</div>
        <select className={`${selectCls} w-full`} value=""
          onChange={(e) => { const id = Number(e.target.value); if (id && !sel.includes(id)) set([...sel, id]) }}>
          <option value="">+ add…</option>
          {opts.filter((o) => !sel.includes(o.id)).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        {sel.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {sel.map((id) => (
              <span key={id} className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-700">
                {opts.find((o) => o.id === id)?.name ?? `#${id}`}
                <button onClick={() => set(sel.filter((x) => x !== id))} className="text-violet-400">✕</button>
              </span>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="p-3">
      <h1 className="mb-3 text-xl font-bold">📊 Analytics</h1>

      {error && <p className="mb-3 rounded-xl bg-red-50 p-3 text-center text-red-600 shadow ring-1 ring-red-200">{error}</p>}

      {/* period */}
      <PeriodFilter start={start} end={end} onChange={setRange} />

      {/* KPI strip */}
      <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {KPIS.map((m) => {
          const s = kpis[m]; const up = (s?.pct_change ?? 0) >= 0
          return (
            <div key={m} className="rounded-xl bg-white p-3 shadow">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">{M(m).label}</div>
              <div className="mt-0.5 text-lg font-bold">{s ? fmt(s.kind, s.current) : '—'}</div>
              {s?.pct_change !== null && s?.pct_change !== undefined && (
                <div className={`text-[11px] font-medium ${up ? 'text-green-600' : 'text-red-600'}`}>{up ? '▲' : '▼'} {Math.abs(s.pct_change)}%</div>
              )}
            </div>
          )
        })}
      </div>

      {/* ------- Explorer ------- */}
      <div className="rounded-2xl bg-slate-50 p-3">
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          Metrics <span className="font-normal normal-case text-slate-400">— the Y axis (pick one or more to compare)</span>
        </div>
        <div className="mb-3 flex flex-wrap gap-2">
          {METRICS.map((m) => <Chip key={m.key} on={metrics.includes(m.key)} onClick={() => toggleMetric(m.key)}>{m.label}</Chip>)}
        </div>

        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          Breakdown <span className="font-normal normal-case text-slate-400">— the X axis</span>
        </div>
        <div className="mb-3 flex flex-wrap gap-2">
          {breakdownOptions.map((b) => (
            <Chip key={b} on={breakdown === b} onClick={() => setBreakdown(b)}>
              {b === 'total' ? 'Total' : b === 'time' ? 'Over time' : DIM_LABEL[b]}
            </Chip>
          ))}
        </div>

        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          Filters <span className="font-normal normal-case text-slate-400">— narrow the data</span>
        </div>
        {filterDims.length === 0 ? (
          <p className="mb-3 text-xs text-slate-400">No filters for the selected metric(s).</p>
        ) : (
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {filterDims.map((dim) => <DimFilter key={dim} dim={dim} />)}
          </div>
        )}

        {/* totals per metric */}
        <div className="mb-3 flex flex-wrap gap-4">
          {metrics.map((m, i) => {
            const t = totals[m]; const up = (t?.pct_change ?? 0) >= 0
            return (
              <div key={m} className="flex items-baseline gap-2">
                <span className="inline-block h-3 w-3 rounded-full" style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
                <span className="text-2xl font-bold">{t ? fmt(M(m).kind, t.current) : '—'}</span>
                <span className="text-xs text-slate-500">{M(m).label}</span>
                {t?.pct_change !== null && t?.pct_change !== undefined && (
                  <span className={`text-xs font-medium ${up ? 'text-green-600' : 'text-red-600'}`}>{up ? '▲' : '▼'} {Math.abs(t.pct_change)}%</span>
                )}
              </div>
            )
          })}
        </div>

        {breakdown !== 'total' && (
          rows.length === 0 ? (
            <p className="rounded-xl bg-white py-8 text-center text-sm text-slate-400 shadow">No data for this selection.</p>
          ) : (
            <>
              <div className="rounded-xl bg-white p-3 shadow">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={rows} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="__label" fontSize={11} tickLine={false} interval={0}
                      angle={rows.length > 6 ? -25 : 0} textAnchor={rows.length > 6 ? 'end' : 'middle'} height={rows.length > 6 ? 54 : 24} />
                    <YAxis fontSize={11} tickLine={false} axisLine={false} width={44} />
                    <Tooltip />
                    {metrics.length > 1 && <Legend />}
                    {metrics.map((m, i) => (
                      <Bar key={m} dataKey={m} name={M(m).label} fill={SERIES_COLORS[i % SERIES_COLORS.length]} radius={[4, 4, 0, 0]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 overflow-x-auto rounded-xl bg-white shadow">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
                      <th className="px-3 py-2 font-semibold">{breakdown === 'time' ? 'Period' : DIM_LABEL[breakdown]}</th>
                      {metrics.map((m) => <th key={m} className="px-3 py-2 text-right font-semibold">{M(m).label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={String(r.__key)} className="border-b border-slate-50">
                        <td className="px-3 py-2 text-slate-600">{r.__label}</td>
                        {metrics.map((m) => <td key={m} className="px-3 py-2 text-right font-semibold tabular-nums">{fmt(M(m).kind, r[m] as number)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )
        )}
      </div>

    </div>
  )
}