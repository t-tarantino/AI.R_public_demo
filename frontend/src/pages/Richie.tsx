import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeftRight, Boxes, ClipboardCopy, Clock, PartyPopper, Receipt,
  type LucideIcon,
} from 'lucide-react'
import { api } from '../api'
import { useCanEdit } from '../lib/user'

interface OrderResult {
  index: number; label: string; status: string
  created_order_id: number | null; created_expense_id: number | null; created_id: number | null
  contents: string
  computed_total: string | null; messages: string[]
}
interface Report {
  committed: boolean; counts: Record<string, number>
  computed_gross_total: string; computed_net_total: string
  stated_gross_total: string | null; stated_net_total: string | null
  checksum_ok: boolean | null; messages: string[]; orders: OrderResult[]
}

type Kind = 'orders' | 'expenses' | 'stock' | 'work' | 'transfers'

// Same icons as the manual quick-add (+) menu, so the two inputs feel like one.
const ICONS: Record<Kind, LucideIcon> = {
  orders: PartyPopper, expenses: Receipt, stock: Boxes, work: Clock, transfers: ArrowLeftRight,
}
const KINDS: Kind[] = ['orders', 'expenses', 'stock', 'work', 'transfers']

const STATUS: Record<string, { label: string; cls: string }> = {
  ok: { label: 'OK', cls: 'bg-green-100 text-green-700' },
  doubt: { label: 'Doubt', cls: 'bg-amber-100 text-amber-700' },
  error: { label: 'Error', cls: 'bg-red-100 text-red-700' },
  duplicate: { label: 'Duplicate', cls: 'bg-slate-200 text-slate-600' },
}

const COPY: Record<Kind, { title: string; create: string; placeholder: string; done: string; link: string; to: string }> = {
  orders: {
    title: 'Orders', create: 'Create drafts', to: '/order', link: 'Go to orders',
    placeholder: '{ "schema_version": 1, "kind": "orders_batch", "orders": [ … ] }',
    done: 'drafts',
  },
  expenses: {
    title: 'Expenses', create: 'Create expenses', to: '/expense', link: 'Go to expenses',
    placeholder: '{ "schema_version": 1, "kind": "expenses_batch", "expenses": [ … ] }',
    done: 'expenses',
  },
  stock: {
    title: 'Stock', create: 'Create updates', to: '/stock', link: 'Go to stock',
    placeholder: '{ "schema_version": 1, "kind": "stock_batch", "updates": [ … ] }',
    done: 'stock updates',
  },
  work: {
    title: 'Work', create: 'Create sessions', to: '/work', link: 'Go to work',
    placeholder: '{ "schema_version": 1, "kind": "work_batch", "entries": [ … ] }',
    done: 'work sessions',
  },
  transfers: {
    title: 'Transfers', create: 'Create transfers', to: '/money', link: 'Go to money',
    placeholder: '{ "schema_version": 1, "kind": "transfers_batch", "transfers": [ … ] }',
    done: 'transfers',
  },
}

export default function Richie() {
  const canEdit = useCanEdit()
  const [kind, setKind] = useState<Kind>('orders')
  const [text, setText] = useState('')
  const [report, setReport] = useState<Report | null>(null)
  const [previewedText, setPreviewedText] = useState('')   // the text the current report was built from
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [copied, setCopied] = useState(false)
  const c = COPY[kind]

  // The prompt is built by the server from the import spec + live master data.
  useEffect(() => {
    if (!showPrompt) return
    setPrompt('Loading…')
    api.get<{ prompt: string }>(`/api/import/prompt/${kind}`)
      .then((r) => setPrompt(r.prompt))
      .catch((e) => setPrompt(e instanceof Error ? e.message : 'Error'))
  }, [showPrompt, kind])

  const switchKind = (k: Kind) => { setKind(k); setReport(null); setPreviewedText(''); setError(''); setText('') }

  const parseBody = (): unknown => {
    let s = text.trim()
    // drop a markdown ```json … ``` fence the chat might add
    s = s.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
    // mobile keyboards mangle the chars JSON needs; build the classes from code
    // points so no literal smart character lives in the source.
    const cls = (codes: number[]) =>
      new RegExp('[' + codes.map((ch) => String.fromCharCode(ch)).join('') + ']', 'g')
    s = s
      .replace(cls([0x201c, 0x201d, 0x201e, 0x201f, 0x2033, 0x2036]), '"')   // smart double quotes
      .replace(cls([0x2018, 0x2019, 0x201a, 0x201b, 0x2032, 0x2035]), "'")   // smart single quotes
      .replace(cls([0x00a0, 0x2007, 0x202f, 0x2009, 0x200a, 0x2028, 0x2029]), ' ')  // nbsp & exotic spaces
      .replace(cls([0x200b, 0xfeff]), '')                                    // zero-width / BOM
      .replace(/,(\s*[}\]])/g, '$1')                                         // trailing comma
    // ignore any prose before/after the single JSON object
    const first = s.indexOf('{'), last = s.lastIndexOf('}')
    if (first >= 0 && last > first) s = s.slice(first, last + 1)
    return JSON.parse(s)
  }

  const run = async (commit: boolean) => {
    setBusy(true); setError(''); if (!commit) setReport(null)
    let body: unknown
    try {
      body = parseBody()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`Invalid JSON (${msg}). On mobile, turn off “smart punctuation” in the keyboard settings, or ask the chat for the JSON on a single line.`)
      setBusy(false); return
    }
    try {
      const r = await api.post<Report>(`/api/import/${kind}/${commit ? 'commit' : 'preview'}`, body)
      setReport(r)
      if (!commit) setPreviewedText(text)
    } catch (e) { setError(e instanceof Error ? e.message : 'Error') } finally { setBusy(false) }
  }

  const createdCount = report?.orders.filter((o) => o.created_order_id || o.created_expense_id || o.created_id).length ?? 0
  // Create is only offered AFTER a dry-run of the exact text now in the box, and
  // only if that preview found rows to create (ok + doubt).
  const toCreate = (report?.counts.ok ?? 0) + (report?.counts.doubt ?? 0)
  const canCreate = !!report && !report.committed && text.trim() === previewedText.trim() && toCreate > 0

  return (
    <div className="p-3">
      <h1 className="mb-1 text-xl font-bold">AI.Richie — import</h1>
      <p className="mb-3 text-sm text-slate-500">
        Paste the JSON produced by the chat and run <b>Preview</b> (no writes). Only then can you{' '}
        <b>{c.create}</b>, which saves the OK and Doubt rows (doubts keep their reason in the comment).
        If some rows have errors, fix them and send the whole file again: rows already created are
        skipped as duplicates.
      </p>

      <div className="mb-3 grid grid-cols-5 gap-2">
        {KINDS.map((k) => {
          const Icon = ICONS[k]
          return (
            <button key={k} onClick={() => switchKind(k)}
              className={`flex flex-col items-center gap-1 rounded-lg p-2 text-xs font-semibold ${kind === k ? 'bg-violet-600 text-white' : 'border border-violet-300 text-violet-700'}`}>
              <Icon size={18} />
              {COPY[k].title}
            </button>
          )
        })}
      </div>

      <button onClick={() => setShowPrompt((v) => !v)} className="mb-2 text-sm font-medium text-violet-600">
        {showPrompt ? 'Hide' : 'Show'} the chat prompt
      </button>
      {showPrompt && (
        <div className="relative mb-3 rounded-xl bg-slate-900 p-3">
          <button onClick={() => { navigator.clipboard?.writeText(prompt); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
            className="absolute right-2 top-2 flex items-center gap-1 rounded-md bg-white/10 px-2 py-1 text-xs text-white hover:bg-white/20">
            <ClipboardCopy size={13} /> {copied ? 'Copied' : 'Copy'}
          </button>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap pr-16 text-[11px] leading-snug text-slate-200">{prompt}</pre>
        </div>
      )}

      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10}
        placeholder={c.placeholder}
        className="w-full rounded-xl border border-slate-300 bg-white p-3 font-mono text-xs" />

      {error && <p className="mt-2 rounded-xl bg-red-50 p-3 text-sm text-red-600 ring-1 ring-red-200">{error}</p>}

      {canEdit && (
        <div className="mt-3 space-y-2">
          <button onClick={() => run(false)} disabled={busy || !text.trim()}
            className="w-full rounded-lg bg-violet-600 p-3 font-semibold text-white disabled:opacity-50">
            {busy ? '…' : 'Preview (dry-run)'}
          </button>
          {canCreate && (
            <button onClick={() => run(true)} disabled={busy}
              className="w-full rounded-lg border border-violet-300 p-3 font-semibold text-violet-700 disabled:opacity-50">
              {busy ? '…' : `${c.create} (${toCreate})`}
            </button>
          )}
        </div>
      )}
      {report && (
        <div className="mt-4">
          {/* summary */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {(['ok', 'doubt', 'error', 'duplicate'] as const).map((k) => (
              (report.counts[k] ?? 0) > 0 && (
                <span key={k} className={`rounded-full px-2.5 py-1 text-xs font-bold ${STATUS[k].cls}`}>
                  {report.counts[k]} {STATUS[k].label}
                </span>
              )
            ))}
            <span className="ml-auto text-sm text-slate-500">
              net <b>€{report.computed_net_total}</b>
              {report.checksum_ok === true && <span className="ml-1 text-green-600">✓ matches</span>}
              {report.checksum_ok === false && <span className="ml-1 text-red-600">✗ doesn't match the stated totals</span>}
            </span>
          </div>
          {report.messages.length > 0 && (
            <ul className="mb-3 space-y-0.5 rounded-xl bg-amber-50 p-3 ring-1 ring-amber-200">
              {report.messages.map((m, i) => <li key={i} className="text-xs text-amber-700">• {m}</li>)}
            </ul>
          )}
          {report.committed && (
            <p className="mb-3 rounded-xl bg-green-50 p-3 text-sm text-green-700 ring-1 ring-green-200">
              Created {createdCount} {c.done}. <Link to={c.to} className="font-semibold underline">{c.link}</Link> to review them.
            </p>
          )}

          {/* per-order results */}
          <ul className="space-y-2">
            {report.orders.map((o) => (
              <li key={o.index} className="rounded-xl bg-white p-3 shadow">
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${STATUS[o.status]?.cls ?? ''}`}>
                    {STATUS[o.status]?.label ?? o.status}
                  </span>
                  <span className="font-semibold">{o.label}</span>
                  {o.computed_total && <span className="ml-auto text-sm font-medium text-slate-500">€{o.computed_total}</span>}
                </div>
                <div className="mt-1 text-xs text-slate-500">{o.contents}</div>
                {o.messages.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5">
                    {o.messages.map((m, i) => <li key={i} className="text-[11px] text-amber-700">• {m}</li>)}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
