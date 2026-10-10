import { useEffect, useState } from 'react'
import { Download, FileText, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { useCanEdit } from '../lib/user'

interface Report {
  monthly_report_id: number
  year: number
  month: number
  label: string
  status: 'final' | 'provisional'
  generated_at: string
  revenue_total: string
  expense_total: string
  transfer_total: string
  profit_total: string
  order_count: number
  expense_count: number
  transfer_count: number
  has_pdf: boolean
}

const eur = (x: string) => `€${Number(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export default function Reports() {
  const canEdit = useCanEdit()
  const [reports, setReports] = useState<Report[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const load = () => api.get<Report[]>('/api/monthly_report').then(setReports).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const now = new Date()
  const hasCurrent = reports.some((r) => r.year === now.getFullYear() && r.month === now.getMonth() + 1)

  const regenerate = (r: Report) => {
    const msg = r.has_pdf
      ? 'Are you sure you want to regenerate this file?\n\nThe previous version of the file will be permanently lost. It is recommended to save the previous version first.'
      : 'This report has no stored PDF. Generate it now from the current data?'
    if (confirm(msg)) generate(r.year, r.month)
  }

  const generate = async (year: number, month: number) => {
    const key = `${year}-${month}`
    setBusy(key); setError('')
    try {
      await api.post(`/api/monthly_report/${year}/${month}/generate`)
      await load()
    } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }

  const downloadPdf = (r: Report) => {
    window.open(`/api/monthly_report/${r.year}/${r.month}/pdf`, '_blank')
  }

  return (
    <div className="p-3">
      <h1 className="mb-1 text-xl font-bold">Monthly reports</h1>
      <p className="mb-3 text-sm text-slate-500">
        A complete snapshot of every month's money flows. A report never changes on its
        own: once created, it is only replaced if you press Regenerate.
      </p>

      {error && <p className="mb-3 rounded-xl bg-red-50 p-3 text-sm text-red-600 shadow ring-1 ring-red-200">{error}</p>}

      {/* current month: generate if not present yet */}
      {!hasCurrent && canEdit && (
        <button onClick={() => generate(now.getFullYear(), now.getMonth() + 1)}
          disabled={busy !== null}
          className="mb-4 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-violet-300 bg-violet-50 p-3 text-sm font-semibold text-violet-700 disabled:opacity-50">
          <FileText size={18} /> Generate current month report
        </button>
      )}

      {reports.length === 0 && !error && (
        <p className="rounded-xl bg-white p-4 text-sm text-slate-400 shadow">No reports available yet.</p>
      )}

      <div className="space-y-3">
        {reports.map((r) => {
          const key = `${r.year}-${r.month}`
          const profit = Number(r.profit_total)
          return (
            <section key={r.monthly_report_id} className="overflow-hidden rounded-xl bg-white shadow">
              <div className="flex items-center justify-between bg-gradient-to-r from-violet-500 to-sky-400 px-4 py-2.5">
                <span className="font-bold text-white">{r.label}</span>
                <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide ${r.status === 'final' ? 'bg-white/25 text-white' : 'bg-amber-300 text-amber-900'}`}>
                  {r.status === 'final' ? 'Final' : 'Provisional'}
                </span>
              </div>

              <div className="grid grid-cols-4 divide-x divide-slate-100 border-b border-slate-100 text-center">
                <Cell label="Revenue" value={eur(r.revenue_total)} sub={`${r.order_count} orders`} />
                <Cell label="Expenses" value={eur(r.expense_total)} sub={`${r.expense_count} expenses`} />
                <Cell label="Profit" value={eur(r.profit_total)} accent={profit < 0 ? 'text-red-600' : 'text-green-700'} />
                <Cell label="Transfers" value={eur(r.transfer_total)} sub={`${r.transfer_count} moves`} />
              </div>

              <div className="flex items-center justify-between px-4 py-2.5">
                <span className="text-[11px] text-slate-400">
                  updated {new Date(r.generated_at).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })}
                </span>
                <div className="flex items-center gap-2">
                  {canEdit && (
                    <button onClick={() => regenerate(r)} disabled={busy !== null}
                      className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-50">
                      <RefreshCw size={14} className={busy === key ? 'animate-spin' : ''} /> Regenerate
                    </button>
                  )}
                  <button onClick={() => downloadPdf(r)} disabled={!r.has_pdf}
                    title={r.has_pdf ? undefined : 'No stored PDF: use Regenerate to create it'}
                    className="flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">
                    <Download size={14} /> PDF
                  </button>
                </div>
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}

function Cell({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="px-1 py-3">
      <div className="text-[10px] uppercase text-slate-400">{label}</div>
      <div className={`text-sm font-bold ${accent ?? 'text-slate-700'}`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-400">{sub}</div>}
    </div>
  )
}
