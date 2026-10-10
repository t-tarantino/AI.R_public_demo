import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { formatDate, useOptions } from '../lib/useOptions'

interface OrderLite {
  customer_order_id: number; location_id: number; date: string; state: string
  items: { composition_id: number }[]
}
interface WorkLite { work_id: number; party_id: number; start_at: string | null; end_at: string | null }

const inputCls = 'mt-1 w-full rounded-lg border border-slate-300 bg-white p-3'
const pad = (n: number) => String(n).padStart(2, '0')
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` }
const addDays = (iso: string, n: number) => {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(y, m - 1, d + n)
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`
}
const HOURS = Array.from({ length: 24 }, (_, h) => pad(h))   // 00..23 (no AM/PM)
const MINUTES = Array.from({ length: 12 }, (_, i) => pad(i * 5))  // 5-minute steps
const toMin = (t: string) => { const [h, m] = t.split(':').map(Number); return h * 60 + m }

// Defined at module scope (NOT inside WorkForm): a component created during
// render gets a new identity each render, which remounts the <select>s on every
// state change (flicker / dropdown closing). Hoisting keeps them stable.
function TimePicker({ h, m, setH, setM }: { h: string; m: string; setH: (v: string) => void; setM: (v: string) => void }) {
  return (
    <div className="mt-1 flex gap-2">
      <select className="w-full rounded-lg border border-slate-300 bg-white p-3" value={h} onChange={(e) => setH(e.target.value)}>
        <option value="">hh</option>
        {HOURS.map((x) => <option key={x} value={x}>{x}</option>)}
      </select>
      <select className="w-full rounded-lg border border-slate-300 bg-white p-3" value={m} onChange={(e) => setM(e.target.value)}>
        <option value="">mm</option>
        {MINUTES.map((x) => <option key={x} value={x}>{x}</option>)}
      </select>
    </div>
  )
}

export default function WorkForm() {
  const { id } = useParams()
  const isNew = id === undefined
  const navigate = useNavigate()

  const [workers, setWorkers] = useState<number[]>([])
  const [date, setDate] = useState<string>(todayISO())
  const [startH, setStartH] = useState(''); const [startM, setStartM] = useState('')
  const [endH, setEndH] = useState(''); const [endM, setEndM] = useState('')
  const [breakMin, setBreakMin] = useState('')
  const [tasks, setTasks] = useState('')
  const [orderIds, setOrderIds] = useState<number[]>([])
  const [existingWork, setExistingWork] = useState<WorkLite[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const parties = useOptions<{ party_id: number; name: string; is_worker: boolean }>('/api/party')
  const orders = useOptions<OrderLite>('/api/order')
  const locations = useOptions<{ location_id: number; name: string }>('/api/location')
  const comps = useOptions<{ composition_id: number; name: string }>('/api/composition')
  const workerList = parties.filter((p) => p.is_worker)
  const pname = (pid: number) => parties.find((p) => p.party_id === pid)?.name ?? `#${pid}`
  const locName = (lid: number) => locations.find((l) => l.location_id === lid)?.name ?? `#${lid}`
  const compName = (cid: number) => comps.find((c) => c.composition_id === cid)?.name ?? `#${cid}`

  const startTime = startH && startM ? `${startH}:${startM}` : ''
  const endTime = endH && endM ? `${endH}:${endM}` : ''

  useEffect(() => { api.get<WorkLite[]>('/api/work').then(setExistingWork).catch(() => {}) }, [])

  useEffect(() => {
    if (isNew) return
    api.get<Record<string, unknown>>(`/api/work/${id}`).then((w) => {
      const s = (w.start_at as string) || '', e = (w.end_at as string) || ''
      setDate((s || e || todayISO()).slice(0, 10))
      if (s) { setStartH(s.slice(11, 13)); setStartM(s.slice(14, 16)) }
      if (e) { setEndH(e.slice(11, 13)); setEndM(e.slice(14, 16)) }
      setBreakMin(w.break_minutes === null ? '' : String(w.break_minutes))
      setTasks((w.tasks_accomplished as string) ?? '')
      setWorkers([w.party_id as number])
      setOrderIds((w.order_ids as number[]) ?? [])
    }).catch((e) => setError(e.message))
  }, [id, isNew])

  // Candidate orders: not cancelled, dated between the session day and +6 days.
  const candidateOrders = useMemo(() =>
    orders.filter((o) => o.state !== 'cancelled' && o.date >= date && o.date < addDays(date, 7))
      .sort((a, b) => a.date.localeCompare(b.date) || locName(a.location_id).localeCompare(locName(b.location_id))),
    [orders, date, locations])

  // New session: default the order selection to the orders of the session day.
  useEffect(() => {
    if (!isNew || orders.length === 0) return
    setOrderIds(orders.filter((o) => o.state !== 'cancelled' && o.date === date).map((o) => o.customer_order_id))
  }, [date, orders.length, isNew])

  const toggleWorker = (pid: number) =>
    setWorkers((ws) => (ws.includes(pid) ? ws.filter((x) => x !== pid) : [...ws, pid]))
  const toggleOrder = (oid: number) =>
    setOrderIds((ids) => (ids.includes(oid) ? ids.filter((x) => x !== oid) : [...ids, oid]))

  // --- soft checks -----------------------------------------------------------
  const endBeforeStart = startTime !== '' && endTime !== '' && toMin(endTime) <= toMin(startTime)
  const workedMin = startTime && endTime ? toMin(endTime) - toMin(startTime) : null
  const breakTooLong = workedMin !== null && breakMin !== '' && Number(breakMin) >= workedMin
  const overlaps = useMemo(() => {
    if (!startTime || !endTime || endBeforeStart) return [] as string[]
    const start = new Date(`${date}T${startTime}`), end = new Date(`${date}T${endTime}`)
    const names: string[] = []
    for (const pid of workers) {
      const clash = existingWork.some((w) => w.work_id !== Number(id) && w.party_id === pid
        && w.start_at && w.end_at && new Date(w.start_at) < end && start < new Date(w.end_at))
      if (clash) names.push(pname(pid))
    }
    return names
  }, [workers, existingWork, date, startTime, endTime, id, parties])

  const orderLabel = (o: OrderLite) => {
    const cs = [...new Set(o.items.map((i) => compName(i.composition_id)))].join(', ')
    return `${formatDate(o.date)} · ${locName(o.location_id)}${cs ? ` · ${cs}` : ''}`
  }

  const save = async () => {
    setError('')
    if (workers.length === 0) { setError('Pick at least one worker.'); return }
    if (endBeforeStart) { setError('End must be after start.'); return }
    setBusy(true)
    const base = {
      order_ids: orderIds,
      start_at: startTime ? `${date}T${startTime}:00` : null,
      end_at: endTime ? `${date}T${endTime}:00` : null,
      break_minutes: breakMin === '' ? null : Number(breakMin),
      tasks_accomplished: tasks || null,
    }
    try {
      if (!isNew) await api.patch(`/api/work/${id}`, { party_id: workers[0], ...base })
      else if (workers.length === 1) await api.post('/api/work', { party_id: workers[0], ...base })
      else await api.post('/api/work/bulk', { party_ids: workers, ...base })
      navigate('/work')
    } catch (e) { setError(e instanceof Error ? e.message : 'Error') } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!confirm('Delete this work session? This cannot be undone.')) return
    setBusy(true); setError('')
    try {
      await api.delete(`/api/work/${id}`)
      navigate('/work')
    } catch (e) { setError(e instanceof Error ? e.message : 'Error') } finally { setBusy(false) }
  }

  return (
    <div className="p-3">
      <h1 className="mb-4 text-xl font-bold">{isNew ? 'New session' : 'Session'}</h1>
      <div className="space-y-4 rounded-xl bg-white p-4 shadow">
        {isNew ? (
          <div>
            <span className="text-sm font-medium">Workers *</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {workerList.map((p) => (
                <button key={p.party_id} type="button" onClick={() => toggleWorker(p.party_id)}
                  className={`rounded-full px-3 py-1.5 text-sm font-medium ${workers.includes(p.party_id) ? 'bg-violet-600 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200'}`}>
                  {p.name}
                </button>
              ))}
            </div>
            <p className="mt-1 text-xs text-slate-400">{workers.length} selected — one session each.</p>
          </div>
        ) : (
          <label className="block"><span className="text-sm font-medium">Worker *</span>
            <select className={inputCls} value={workers[0] ?? ''}
              onChange={(e) => setWorkers(e.target.value === '' ? [] : [Number(e.target.value)])}>
              <option value="">— choose —</option>
              {workerList.map((p) => <option key={p.party_id} value={p.party_id}>{p.name}</option>)}
            </select>
          </label>
        )}

        <label className="block"><span className="text-sm font-medium">Date *</span>
          <input type="date" className={inputCls} value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <div><span className="text-sm font-medium">Start</span>
            <TimePicker h={startH} m={startM} setH={setStartH} setM={setStartM} />
          </div>
          <div><span className="text-sm font-medium">End</span>
            <TimePicker h={endH} m={endM} setH={setEndH} setM={setEndM} />
          </div>
        </div>
        <label className="block"><span className="text-sm font-medium">Break (minutes)</span>
          <input className={inputCls} inputMode="numeric" value={breakMin}
            onChange={(e) => setBreakMin(e.target.value)} />
        </label>

        <div>
          <span className="text-sm font-medium">Orders <span className="font-normal text-slate-400">— same day and next 6</span></span>
          {candidateOrders.length === 0 ? (
            <p className="mt-1 text-xs text-slate-400">No orders in this range (internal work).</p>
          ) : (
            <div className="mt-1 flex flex-col gap-1.5">
              {candidateOrders.map((o) => {
                const on = orderIds.includes(o.customer_order_id)
                return (
                  <button key={o.customer_order_id} type="button" onClick={() => toggleOrder(o.customer_order_id)}
                    className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm ${on ? 'bg-violet-50 ring-1 ring-violet-300' : 'bg-white ring-1 ring-slate-200'}`}>
                    <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded ${on ? 'bg-violet-600 text-white' : 'ring-1 ring-slate-300'}`}>{on ? '✓' : ''}</span>
                    <span className="min-w-0 flex-1 truncate">{orderLabel(o)}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        <label className="block"><span className="text-sm font-medium">Tasks done</span>
          <textarea className={inputCls} rows={2} value={tasks} onChange={(e) => setTasks(e.target.value)} />
        </label>

        {endBeforeStart && <p className="text-sm text-red-600">⚠ End must be after start.</p>}
        {breakTooLong && <p className="text-sm text-amber-600">⚠ Break is ≥ the session length.</p>}
        {overlaps.length > 0 && (
          <p className="text-sm text-amber-600">⚠ Overlap: {overlaps.join(', ')} already {overlaps.length === 1 ? 'has' : 'have'} a session at that time.</p>
        )}
      </div>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      <div className="mt-4 flex gap-3">
        <button onClick={save} disabled={busy}
          className="flex-1 rounded-lg bg-violet-600 p-3 font-semibold text-white disabled:opacity-50">
          {busy ? 'Saving…' : (isNew && workers.length > 1 ? `Save (${workers.length})` : 'Save')}
        </button>
        {!isNew && (
          <button onClick={remove} disabled={busy}
            className="rounded-lg bg-red-600 px-4 font-semibold text-white disabled:opacity-50">Delete</button>
        )}
        <button onClick={() => navigate('/work')} className="rounded-lg border border-slate-300 px-4 font-medium">Cancel</button>
      </div>
    </div>
  )
}
