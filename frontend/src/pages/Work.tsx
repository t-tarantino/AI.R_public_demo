import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronRight, Pencil, User } from 'lucide-react'
import { api } from '../api'
import { formatDateWithDay, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'
import PeriodFilter, { currentMonthRange } from '../components/PeriodFilter'

interface WorkRow {
  work_id: number
  party_id: number
  order_ids: number[]
  start_at: string | null
  end_at: string | null
  break_minutes: number | null
  tasks_accomplished: string | null
}

const time = (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

// Format a minute count as "17h 36m" / "6h 12m" / "45m" — hours plus minutes
// only when there are any, so we never show misleading decimals like "17.6h".
function hm(mins: number): string {
  const h = Math.floor(mins / 60)
  const m = Math.round(mins % 60)
  return h ? `${h}h${m ? ` ${m}m` : ''}` : `${m}m`
}

function duration(w: WorkRow): string | null {
  if (!w.start_at || !w.end_at) return null
  const mins = (new Date(w.end_at).getTime() - new Date(w.start_at).getTime()) / 60000 - (w.break_minutes ?? 0)
  if (mins <= 0) return null
  return hm(mins)
}

// A work session belongs to a day via its start date (fallback: '—').
const dayOf = (w: WorkRow) => (w.start_at ? w.start_at.slice(0, 10) : '—')

export default function Work() {
  const canEdit = useCanEdit()
  const [rows, setRows] = useState<WorkRow[]>([])
  const [[start, end], setRange] = useState<[string, string]>(currentMonthRange())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const parties = useOptions<{ party_id: number; name: string; code_nickname?: string | null; is_worker?: boolean; credit_hours?: string | number | null; hidden_from_ranking?: boolean }>('/api/party')
  const name = (id: number) => parties.find((p) => p.party_id === id)?.name ?? `#${id}`
  // The ranking board shows siglas (e.g. AL) rather than full names; falls back to the name.
  const code = (id: number) => { const p = parties.find((p) => p.party_id === id); return p?.code_nickname ?? p?.name ?? `#${id}` }

  useEffect(() => {
    setLoading(true)
    api.get<WorkRow[]>('/api/work')
      .then((data) => { setRows(data); setError(null) })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  // Sessions whose day falls inside the selected period.
  const visibleRows = useMemo(
    () => rows.filter((w) => { const d = dayOf(w); return d !== '—' && d >= start && d <= end }),
    [rows, start, end],
  )

  // date -> worker -> sessions
  const groups = useMemo(() => {
    const byDate = new Map<string, Map<number, WorkRow[]>>()
    for (const w of visibleRows) {
      const d = dayOf(w)
      const byWorker = byDate.get(d) ?? new Map<number, WorkRow[]>()
      const list = byWorker.get(w.party_id) ?? []
      list.push(w)
      byWorker.set(w.party_id, list)
      byDate.set(d, byWorker)
    }
    return [...byDate.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([date, byWorker]) => [
        date,
        [...byWorker.entries()].sort((a, b) => name(a[0]).localeCompare(name(b[0]))),
      ] as const)
  }, [visibleRows, parties])

  // The ranking board is intentionally ALL-TIME: it ignores the period filter
  // above (which only scopes the day-by-day list below). We only care about
  // workers' relative standing, so no absolute hours are shown — just the order,
  // a relative bar (leader = full) and the gap behind the leader. Manual
  // `credit_hours` on a worker are folded into the total here (and nowhere else)
  // and shown as their own pill so they stay visible/editable.
  const summary = useMemo(() => {
    const creditMinsOf = (pid: number) => Number(parties.find((p) => p.party_id === pid)?.credit_hours ?? 0) * 60
    const mins = new Map<number, number>()
    for (const w of rows) {
      if (!w.start_at || !w.end_at) continue
      const m = (new Date(w.end_at).getTime() - new Date(w.start_at).getTime()) / 60000 - (w.break_minutes ?? 0)
      if (m > 0) mins.set(w.party_id, (mins.get(w.party_id) ?? 0) + m)
    }
    // Fold in manual credit hours; seed credit-only workers who never logged a session.
    for (const p of parties) {
      const credit = Number(p.credit_hours ?? 0) * 60
      if (credit > 0 && (p.is_worker || mins.has(p.party_id))) {
        mins.set(p.party_id, (mins.get(p.party_id) ?? 0) + credit)
      }
    }
    // Workers flagged as hidden are excluded from the board (so they don't
    // affect the ranking order, the leader, or the gaps).
    const hidden = new Set(parties.filter((p) => p.hidden_from_ranking).map((p) => p.party_id))
    const arr = [...mins.entries()].filter(([pid]) => !hidden.has(pid)).map(([pid, m]) => ({ pid, name: code(pid), mins: m }))
    arr.sort((a, b) => b.mins - a.mins)
    // Bar widths: the leader fills the bar (100%). The LAST worker's length is a
    // saturating (hyperbolic) function of the TOTAL gap, so the bars convey the
    // real magnitude of the spread — a small total gap keeps every bar long
    // ("not much"), a big one makes the last bar short ("a lot") — while never
    // overflowing or hitting zero. Everyone in between is placed LINEARLY by
    // their gap, so differences stay proportional to the hours.
    const SPREAD_K = 240  // minutes; tuned so a 1h total gap => last bar at 80%
    const MIN_BAR = 1 / 20  // floor so even a huge spread keeps the last bar visible
    const max = arr.length ? arr[0].mins : 0
    const min = arr.length ? arr[arr.length - 1].mins : 0
    const span = max - min
    const lastFrac = span > 0 ? Math.max(MIN_BAR, 1 / (1 + span / SPREAD_K)) : 1
    return arr.map((w) => {
      const creditMins = creditMinsOf(w.pid)
      return {
        ...w,
        pct: span > 0 ? (lastFrac + (1 - lastFrac) * (w.mins - min) / span) * 100 : 100,
        deficitLabel: max - w.mins > 0 ? `−${hm(max - w.mins)}` : '',
        creditLabel: creditMins > 0 ? `+${hm(creditMins)}` : '',
      }
    })
  }, [rows, parties])

  // Light footer line reporting who has credit hours (kept off the rows for a
  // compact, phone-friendly board). Empty string when nobody has any.
  const creditSummary = summary.filter((w) => w.creditLabel).map((w) => `${w.name} ${w.creditLabel}`).join(', ')

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">🕒 Work hours</h1>
        {canEdit && <Link to="/work/new" className="rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white">+ Work Time</Link>}
      </div>

      <PeriodFilter start={start} end={end} onChange={setRange} />

      {loading && <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">Loading…</p>}
      {!loading && error && (
        <p className="rounded-xl bg-white p-6 text-center text-red-600 shadow">Failed to load work sessions: {error}</p>
      )}
      {!loading && !error && rows.length === 0 && (
        <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">No sessions.</p>
      )}

      {summary.length > 0 && (
        <div className="mb-4 rounded-xl bg-white p-3 shadow">
          <h2 className="text-sm font-semibold text-slate-600">Worker ranking</h2>
          <p className="mb-3 text-xs text-slate-400">All-time standing. Light bar = gap behind the leader.</p>
          <div className="space-y-2.5">
            {summary.map((w) => (
              <div key={w.pid} className="flex items-center gap-2.5">
                <span className="w-10 shrink-0 truncate text-right text-xs font-medium text-slate-600">{w.name}</span>
                <div className="h-5 min-w-0 flex-1 overflow-hidden rounded-md bg-sky-100">
                  <div className="h-full rounded-md bg-violet-600" style={{ width: `${w.pct}%` }} />
                </div>
                <span className="w-[84px] shrink-0 text-center tabular-nums">
                  {w.deficitLabel ? (
                    <span className="whitespace-nowrap rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-semibold text-sky-600">
                      {w.deficitLabel}
                    </span>
                  ) : (
                    <span className="whitespace-nowrap rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-600">
                      Top
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>

          <div className="mt-3 flex items-start gap-1.5 text-[11px] leading-snug text-slate-400">
            <span className="min-w-0">
              Credit hours{creditSummary ? `: ${creditSummary}` : ': none'}
            </span>
            {canEdit && (
              <button
                onClick={() => navigate('/e/party')}
                title="Edit credit hours in master data"
                className="mt-px shrink-0 rounded p-0.5 text-slate-400 hover:text-violet-600"
              >
                <Pencil size={12} />
              </button>
            )}
          </div>
        </div>
      )}

      <div className="space-y-4">
        {groups.map(([date, byWorker]) => (
          <section key={date} className="overflow-hidden rounded-xl bg-white shadow">
            <div className="bg-gradient-to-r from-violet-500 to-sky-400 px-3 py-2">
              <span className="rounded-full bg-white/25 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-white">
                {date === '—' ? 'No date' : formatDateWithDay(date)}
              </span>
            </div>

            <div className="space-y-2 p-2">
              {byWorker.map(([workerId, sessions]) => (
                <div key={workerId} className="overflow-hidden rounded-lg border border-violet-100">
                  <div className="flex items-center gap-1 bg-violet-100 px-2.5 py-1.5">
                    <User size={13} className="shrink-0 text-violet-500" />
                    <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs font-semibold text-violet-800">
                      {name(workerId)}
                    </span>
                  </div>

                  <div className="space-y-1.5 bg-violet-50/40 p-1.5">
                    {sessions.map((w) => {
                      const dur = duration(w)
                      return (
                        <div
                          key={w.work_id}
                          onClick={() => navigate(`/work/${w.work_id}`)}
                          className="flex cursor-pointer items-start gap-2 rounded-md bg-white p-2 shadow-sm hover:bg-violet-50"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                              <span>{w.start_at && w.end_at ? `${time(w.start_at)} – ${time(w.end_at)}` : '—'}</span>
                              {w.order_ids.map((oid) => (
                                <span key={oid} className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700">
                                  Order #{oid}
                                </span>
                              ))}
                            </div>
                            {w.tasks_accomplished && (
                              <div className="mt-0.5 text-xs text-slate-500">{w.tasks_accomplished}</div>
                            )}
                          </div>
                          {dur && (
                            <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">{dur}</span>
                          )}
                          <ChevronRight size={15} className="mt-0.5 shrink-0 text-slate-300" />
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
