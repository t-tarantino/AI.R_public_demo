import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CalendarDays, Clock, Coffee, Pencil, User } from 'lucide-react'
import { api } from '../api'
import { formatDate, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'

interface Work {
  work_id: number
  party_id: number
  order_ids: number[]
  start_at: string | null
  end_at: string | null
  break_minutes: number | null
  tasks_accomplished: string | null
  comment: string | null
}

const time = (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
const hm = (mins: number) => {
  const h = Math.floor(mins / 60), m = Math.round(mins % 60)
  return h ? `${h}h${m ? ` ${m}m` : ''}` : `${m}m`
}

export default function WorkDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const canEdit = useCanEdit()
  const [w, setW] = useState<Work | null>(null)
  const [error, setError] = useState('')
  const parties = useOptions<{ party_id: number; name: string }>('/api/party')
  const partyName = (i: number) => parties.find((p) => p.party_id === i)?.name ?? `#${i}`

  useEffect(() => {
    api.get<Work>(`/api/work/${id}`).then(setW).catch((e) => setError(e.message))
  }, [id])

  if (error) return <p className="p-3 text-sm text-red-600">{error}</p>
  if (!w) return <p className="p-6 text-center text-slate-400">Loading…</p>

  const dur = (() => {
    if (!w.start_at || !w.end_at) return null
    const mins = (new Date(w.end_at).getTime() - new Date(w.start_at).getTime()) / 60000 - (w.break_minutes ?? 0)
    return mins > 0 ? hm(mins) : null
  })()

  return (
    <div className="p-3">
      {/* worker + duration headline */}
      <div className="mb-3 flex items-center justify-between rounded-xl bg-white p-4 shadow">
        <div className="flex items-center gap-2">
          <User size={18} className="text-violet-500" />
          <span className="text-lg font-bold">{partyName(w.party_id)}</span>
        </div>
        {dur && <span className="rounded-full bg-violet-100 px-3 py-1 text-sm font-bold text-violet-700">{dur}</span>}
      </div>

      <div className="space-y-2 rounded-xl bg-white p-3 shadow">
        {w.start_at && (
          <div className="flex items-center gap-2 text-sm">
            <CalendarDays size={16} className="shrink-0 text-slate-400" />
            <span>{formatDate(w.start_at.slice(0, 10))}</span>
          </div>
        )}
        <div className="flex items-center gap-2 text-sm">
          <Clock size={16} className="shrink-0 text-slate-400" />
          <span>{w.start_at && w.end_at ? `${time(w.start_at)} – ${time(w.end_at)}` : '—'}</span>
        </div>
        {w.break_minutes ? (
          <div className="flex items-center gap-2 text-sm">
            <Coffee size={16} className="shrink-0 text-slate-400" />
            <span>{w.break_minutes}m break</span>
          </div>
        ) : null}
        {w.order_ids.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-xs text-slate-400">Orders:</span>
            {w.order_ids.map((oid) => (
              <Link key={oid} to={`/order/${oid}`}
                className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700">Order #{oid}</Link>
            ))}
          </div>
        )}
        {w.tasks_accomplished && <div className="pt-1 text-sm text-slate-600">{w.tasks_accomplished}</div>}
        {w.comment && <div className="text-xs italic text-slate-400">{w.comment}</div>}
      </div>

      {canEdit && (
        <button onClick={() => navigate(`/work/${id}/edit`)}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-violet-600 p-3 font-semibold text-white">
          <Pencil size={18} /> Edit
        </button>
      )}
    </div>
  )
}
