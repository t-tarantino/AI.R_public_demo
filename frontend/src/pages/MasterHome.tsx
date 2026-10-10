import { Link } from 'react-router-dom'
import { Bot, ClipboardList, FileText, Settings } from 'lucide-react'
import { ENTITIES } from '../entities'
import { useCanEdit } from '../lib/user'

const card = 'rounded-xl bg-white p-4 text-center text-sm font-medium shadow hover:bg-violet-50'

export default function MasterHome() {
  const canEdit = useCanEdit()
  return (
    <div className="p-3">
      <h1 className="mb-3 text-xl font-bold">🗄️ Master data</h1>
      <div className="grid grid-cols-2 gap-3">
        {ENTITIES.map((e) => (
          <Link key={e.key} to={`/e/${e.key}`} className={card}>{e.title}</Link>
        ))}
      </div>

      <h2 className="mb-2 mt-6 text-sm font-semibold uppercase text-slate-400">System</h2>
      <div className="grid grid-cols-2 gap-3">
        <Link to="/activity" className={`${card} flex items-center justify-center gap-2`}>
          <ClipboardList size={18} /> Activity
        </Link>
        <Link to="/reports" className={`${card} flex items-center justify-center gap-2`}>
          <FileText size={18} /> Monthly reports
        </Link>
        {canEdit && (
          <Link to="/richie" className={`${card} flex items-center justify-center gap-2`}>
            <Bot size={18} /> Richie (import)
          </Link>
        )}
        <Link to="/settings" className={`${card} flex items-center justify-center gap-2`}>
          <Settings size={18} /> Settings
        </Link>
      </div>
    </div>
  )
}
