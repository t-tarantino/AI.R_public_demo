import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, ChevronRight, Gift, MapPin, Plus, Scale, Store, TrendingDown, TrendingUp } from 'lucide-react'
import { api } from '../api'
import { formatDate, useOptions } from '../lib/useOptions'
import { useCanEdit } from '../lib/user'
import AutoGrid from '../components/AutoGrid'

type WarnLevel = 'red' | 'orange' | 'yellow' | 'ok'
interface StockRow {
  required_item_id: number
  required_item_name: string
  unit: string
  color_id: number | null
  color_name: string | null
  variant: string | null
  quantity: number
  effective_minimum: number | null
  below_minimum: boolean
  consume_next_10: number
  consume_future: number
  level: WarnLevel
}

interface UpdateItem {
  required_item_id: number
  color_id: number | null
  variant: string | null
  quantity_change: number
  customer_order_id: number | null
  expense_item_id: number | null
}
interface ExpenseLite {
  expense_id: number
  paid_to_party_id: number
  items: { expense_item_id: number }[]
}
interface Update {
  inventory_update_id: number
  type: string
  date: string
  comment: string | null
  items: UpdateItem[]
}
interface OrderLite {
  customer_order_id: number
  location_id: number
  items: { composition_id: number }[]
}
// A purchasable SKU, only the fields needed to resolve the "+" reorder button.
interface ProductLite {
  required_item_id: number
  color_id: number | null
  variant: string | null
  product_link: string | null
  is_first_choice: boolean
  active: boolean
}

// --- material domain constants ----------------------------------------------
const GRANDE = 'Palloncino grande'
const PICCOLO = 'Palloncino piccolo'
const LUNGO = 'Palloncino lungo'
// label = short size shown on the chips (L/M/S); 110=L, 80=M, 35=S.
const NUMERO_SIZES = [
  { name: 'Palloncino numero 110', label: 'L' },
  { name: 'Palloncino numero 80', label: 'M' },
  { name: 'Palloncino numero 35', label: 'S' },
]
// Short labels for the history (several materials fit on one line).
const MAT_ABBR: Record<string, string> = {
  'Palloncino grande': 'G', 'Palloncino piccolo': 'P', 'Palloncino lungo': 'L',
  'Palloncino numero 110': 'N110', 'Palloncino numero 80': 'N80', 'Palloncino numero 35': 'N35',
}
// Neutral (colourless) materials get their own grey token with a letter, matching
// the warehouse (L long, E helium) instead of a "—" colour dot.
const NEUTRAL_GLYPH: Record<string, string> = { 'Palloncino lungo': 'L', 'Elio': 'E' }

// --- colour layout (from the catalogue palette) -----------------------------
const BASE_CODES = ['001', '014', '068', '009', '010', '079', '006', '007', '045', '013', '008', '004', '002']
const METAL_CODES = ['089', '096', '054', '064', '088', '028']
const NUMERO_COLOR_CODES = ['088', '089']  // oro / argento (the only regularly-stocked number colours)
const NUMERO_DIGITS = ['1', '8']
// The full domain, revealed only on demand via the "show all variants" toggle,
// so the common view stays small while every variant stays reachable for entry.
const ALL_NUMERO_DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
const ALL_NUMERO_CODES = [...METAL_CODES, ...BASE_CODES]

// Swatch colour per catalogue code (+ known off-catalogue colours).
const HEX: Record<string, string> = {
  '001': '#f3f4f6', '014': '#1f2937', '068': '#14b8a6', '009': '#7dd3fc',
  '010': '#2743a3', '079': '#c4a3d9', '006': '#ec9cbb', '007': '#d6337f',
  '045': '#d92534', '013': '#3ba14f', '008': '#6b3fa0', '004': '#e8892a',
  '002': '#f5c51a', '089': '#c0c4c8', '096': '#c08a72', '054': '#1f4fb0',
  '064': '#c31e6d', '088': '#c8a227', '028': '#eae2d2',
  '101': '#6e1a2e', '102': '#16264d',
}
const PALETTE = new Set([...BASE_CODES, ...METAL_CODES])
// Readable text over a swatch (dark on light colours, else white).
const textOn = (hex: string) => {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16)
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? '#334155' : '#ffffff'
}

// Multi-select categories (no "All": pick any combination; all selected by default).
const HISTORY_TABS: { key: string; label: string; types: string[] }[] = [
  { key: 'consumption', label: 'Consumption', types: ['order_usage'] },
  { key: 'refill', label: 'Refill', types: ['purchase'] },
  { key: 'adjustments', label: 'Adjustments', types: ['recount', 'loss', 'gift'] },
]
const TYPE_META: Record<string, { label: string; Icon: typeof Scale; tint: string }> = {
  order_usage: { label: 'Consumption', Icon: TrendingDown, tint: 'text-red-600' },
  purchase: { label: 'Refill', Icon: TrendingUp, tint: 'text-green-700' },
  recount: { label: 'Recount', Icon: Scale, tint: 'text-slate-600' },
  loss: { label: 'Loss', Icon: AlertTriangle, tint: 'text-amber-600' },
  gift: { label: 'Gift', Icon: Gift, tint: 'text-green-700' },
}
const TYPE_ORDER = ['order_usage', 'purchase', 'recount', 'loss', 'gift']

const subLabel = (color: string | null, variant: string | null) =>
  [color, variant ? `digit ${variant}` : null].filter(Boolean).join(' · ')

// Warning levels (forecast from confirmed orders). Hierarchy red > orange > yellow.
const LEVEL_CHIP: Record<WarnLevel, string> = {
  red: 'bg-red-100 text-red-600',
  orange: 'bg-orange-100 text-orange-700',
  yellow: 'bg-yellow-100 text-yellow-800',
  ok: 'bg-violet-100 text-violet-700',
}
const LEVEL_PILL: Record<Exclude<WarnLevel, 'ok'>, string> = {
  red: 'bg-red-50 text-red-700 ring-red-200',
  orange: 'bg-orange-50 text-orange-700 ring-orange-200',
  yellow: 'bg-yellow-50 text-yellow-800 ring-yellow-200',
}
const LEVEL_DOT: Record<Exclude<WarnLevel, 'ok'>, string> = {
  red: 'bg-red-500', orange: 'bg-orange-500', yellow: 'bg-yellow-400',
}
const LEVEL_LABEL: Record<Exclude<WarnLevel, 'ok'>, string> = {
  red: 'Not enough for the next 10 days',
  orange: 'Below minimum within 10 days',
  yellow: 'Below minimum (future use)',
}
const LEVEL_RANK: Record<WarnLevel, number> = { red: 0, orange: 1, yellow: 2, ok: 3 }
const WARN_LEVELS: Exclude<WarnLevel, 'ok'>[] = ['red', 'orange', 'yellow']

export default function Stock() {
  const canEdit = useCanEdit()
  const [rows, setRows] = useState<StockRow[]>([])
  const [history, setHistory] = useState<Update[]>([])
  // Movement-history filters: category multi-select (all on by default) + the
  // material cells picked by tapping a stock chip.
  const [cats, setCats] = useState<Set<string>>(() => new Set(HISTORY_TABS.map((t) => t.key)))
  const [cellFilters, setCellFilters] = useState<
    { key: string; riId: number; colorId: number | null; variant: string | null; label: string }[]>([])
  const [error, setError] = useState('')
  // Numbers explode combinatorially (digit × colour × size); show only the hot
  // set by default, let the user expand to the full domain to count a rare one.
  const [showAllNumbers, setShowAllNumbers] = useState(false)
  const navigate = useNavigate()
  const historyRef = useRef<HTMLDivElement>(null)
  const toggleCat = (k: string) =>
    setCats((prev) => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n })
  const items = useOptions<{ required_item_id: number; name: string }>('/api/required_item')
  const colors = useOptions<{ color_id: number; code: string; name: string; in_catalog: boolean; swatch_hex?: string | null }>('/api/color')
  const orders = useOptions<OrderLite>('/api/order')
  const expenses = useOptions<ExpenseLite>('/api/expense')
  const parties = useOptions<{ party_id: number; name: string }>('/api/party')
  const locations = useOptions<{ location_id: number; name: string }>('/api/location')
  const comps = useOptions<{ composition_id: number; name: string }>('/api/composition')
  const products = useOptions<ProductLite>('/api/product')
  const riName = (id: number) => items.find((i) => i.required_item_id === id)?.name ?? `#${id}`
  const riAbbr = (id: number) => MAT_ABBR[riName(id)] ?? riName(id)
  const color = (id: number | null) => (id ? colors.find((c) => c.color_id === id) : undefined)
  const colorName = (id: number | null) => color(id)?.name ?? null
  const pname = (id: number) => parties.find((p) => p.party_id === id)?.name ?? `#${id}`
  const locName = (id: number) => locations.find((l) => l.location_id === id)?.name ?? `#${id}`
  const compName = (id: number) => comps.find((c) => c.composition_id === id)?.name ?? `#${id}`
  const colorByCode = useMemo(() => new Map(colors.map((c) => [c.code, c])), [colors])
  const orderById = useMemo(() => new Map(orders.map((o) => [o.customer_order_id, o])), [orders])
  const nameToId = useMemo(() => new Map(items.map((i) => [i.name, i.required_item_id])), [items])
  // First-choice reorder link per stock cell: key "riId|colorId|variant" -> URL.
  // Only active first-choice products that actually carry a link are reachable.
  const firstChoiceLink = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of products) {
      if (p.is_first_choice && p.active && p.product_link)
        m.set(`${p.required_item_id}|${p.color_id ?? ''}|${p.variant ?? ''}`, p.product_link)
    }
    return m
  }, [products])
  const buyLink = (materialName: string, colorId: number | null, variant: string | null) => {
    const riId = nameToId.get(materialName)
    return riId === undefined
      ? undefined
      : firstChoiceLink.get(`${riId}|${colorId ?? ''}|${variant ?? ''}`)
  }
  // expense_item_id -> supplier (paid_to) name, for refill provenance.
  const supplierByExpItem = useMemo(() => {
    const m = new Map<number, string>()
    for (const e of expenses) for (const it of e.items) m.set(it.expense_item_id, pname(e.paid_to_party_id))
    return m
  }, [expenses, parties])

  const orderHeader = (u: Update): { loc: string; comps: string } | null => {
    const oid = u.items.find((it) => it.customer_order_id)?.customer_order_id
    const o = oid ? orderById.get(oid) : undefined
    if (!o) return null
    return { loc: locName(o.location_id), comps: [...new Set(o.items.map((i) => compName(i.composition_id)))].join(', ') }
  }
  // Refill provenance: the supplier the products were bought from.
  const refillSupplier = (u: Update): string | null => {
    const eid = u.items.find((it) => it.expense_item_id)?.expense_item_id
    return eid ? supplierByExpItem.get(eid) ?? null : null
  }

  useEffect(() => {
    api.get<StockRow[]>('/api/stock').then(setRows).catch((e) => setError(e.message))
    api.get<Update[]>('/api/inventory_update').then(setHistory).catch((e) => setError(e.message))
  }, [])

  // Fast lookup: "material|colorId|variant" -> stock row.
  const stockMap = useMemo(() => {
    const m = new Map<string, StockRow>()
    for (const r of rows) m.set(`${r.required_item_name}|${r.color_id ?? ''}|${r.variant ?? ''}`, r)
    return m
  }, [rows])
  const cell = (name: string, colorId: number | null, variant: string | null) =>
    stockMap.get(`${name}|${colorId ?? ''}|${variant ?? ''}`)

  // Forecast warnings (level != ok), sorted by severity then name.
  const warnings = useMemo(
    () => rows.filter((r) => r.level !== 'ok')
      .sort((a, b) => LEVEL_RANK[a.level] - LEVEL_RANK[b.level]
        || a.required_item_name.localeCompare(b.required_item_name)),
    [rows])
  const warnCount = (lvl: WarnLevel) => warnings.filter((r) => r.level === lvl).length

  // Balloon-stock colours not in the curated palette (off-catalogue or extra),
  // so nothing with stock stays hidden.
  const extraColors = useMemo(() => {
    const codes = new Set<string>()
    for (const r of rows) {
      if ((r.required_item_name === GRANDE || r.required_item_name === PICCOLO) && r.color_id) {
        const code = color(r.color_id)?.code
        if (code && !PALETTE.has(code)) codes.add(code)
      }
    }
    return [...codes].sort()
  }, [rows, colors])

  // Individual number cells (colour + digit + size) that hold stock but sit
  // OUTSIDE the curated hot set. One entry per actual cell — these quantities are
  // sparse, so a big three-size bubble would be mostly empty; we render a small
  // bubble per real cell instead. Sorted digit → colour → size (L, M, S).
  const extraNumberCells = useMemo(() => {
    const sizeLabel = new Map(NUMERO_SIZES.map((s) => [s.name, s.label]))
    const sizeOrder = NUMERO_SIZES.map((s) => s.name)
    const out: { digit: string; code: string; sizeName: string; label: string }[] = []
    for (const r of rows) {
      const label = sizeLabel.get(r.required_item_name)
      if (!label || (r.quantity ?? 0) === 0) continue
      const code = color(r.color_id)?.code
      const digit = r.variant
      if (!code || !digit) continue
      if (NUMERO_DIGITS.includes(digit) && NUMERO_COLOR_CODES.includes(code)) continue
      out.push({ digit, code, sizeName: r.required_item_name, label })
    }
    return out.sort((a, b) => a.digit.localeCompare(b.digit) || a.code.localeCompare(b.code)
      || sizeOrder.indexOf(a.sizeName) - sizeOrder.indexOf(b.sizeName))
  }, [rows, colors])

  // How a single line's change is shown: a recount stores the counted ABSOLUTE,
  // so show it as "=n"; loss/gift/etc. are signed deltas "+n/-n".
  const fmtChange = (type: string, _u: Update, it: UpdateItem): string => {
    if (type === 'recount') return `=${it.quantity_change}`
    return `${it.quantity_change > 0 ? '+' : ''}${it.quantity_change}`
  }

  const matchItem = (it: UpdateItem) => cellFilters.some((f) =>
    f.riId === it.required_item_id
    && (f.colorId ?? null) === (it.color_id ?? null)
    && (f.variant ?? null) === (it.variant ?? null))

  const addCellFilter = (materialName: string, colorId: number | null, variant: string | null) => {
    const riId = nameToId.get(materialName)
    if (riId === undefined) return
    const key = `${riId}|${colorId ?? ''}|${variant ?? ''}`
    setCellFilters((prev) => prev.some((f) => f.key === key) ? prev : [...prev, {
      key, riId, colorId, variant,
      label: [materialName, colorName(colorId), variant ? `digit ${variant}` : null]
        .filter(Boolean).join(' · '),
    }])
    setTimeout(() => historyRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }
  const removeCellFilter = (key: string) =>
    setCellFilters((prev) => prev.filter((f) => f.key !== key))

  // Movements for the selected categories + material filters, grouped date -> type.
  const historyByDate = useMemo(() => {
    const types = HISTORY_TABS.filter((t) => cats.has(t.key)).flatMap((t) => t.types)
    const visible = history.filter((u) =>
      types.includes(u.type) && (cellFilters.length === 0 || u.items.some(matchItem)))
    const byDate = new Map<string, Map<string, Update[]>>()
    for (const u of visible) {
      const byType = byDate.get(u.date) ?? new Map<string, Update[]>()
      const list = byType.get(u.type) ?? []
      list.push(u)
      byType.set(u.type, list)
      byDate.set(u.date, byType)
    }
    return [...byDate.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([date, byType]) => [
        date,
        [...byType.entries()].sort((a, b) => TYPE_ORDER.indexOf(a[0]) - TYPE_ORDER.indexOf(b[0])),
      ] as const)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history, cats, cellFilters])

  // Rounded colour circle with the code inside (AI.R style).
  const ColorDot = ({ colorId, big = false }: { colorId: number | null; big?: boolean }) => {
    const c = color(colorId)
    const hex = colorId === null ? '#e2e8f0' : (c?.swatch_hex || HEX[c?.code ?? ''] || '#e5e7eb')
    const code = colorId === null ? '—' : (c?.code ?? '?')
    const sz = big ? 'h-12 w-12 text-[13px]' : 'h-6 w-6 text-[8px]'
    return (
      <span className={`flex ${sz} shrink-0 items-center justify-center rounded-full border border-slate-300 font-bold`}
        style={{ background: hex, color: textOn(hex) }} title={colorName(colorId) ?? 'neutral'}>{code}</span>
    )
  }

  // A small round "+" that opens the first-choice reorder link for a stock cell.
  // Rendered only when such a link exists (active first-choice product with a URL).
  const BuyPlus = ({ link }: { link?: string }) =>
    link ? (
      <button
        type="button"
        title="Buy / reorder"
        onClick={(e) => { e.stopPropagation(); window.open(link, '_blank', 'noopener,noreferrer') }}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 shadow-sm hover:bg-emerald-200"
      >
        <Plus size={13} strokeWidth={3} />
      </button>
    ) : null

  // A quantity chip (violet by default, red when below minimum) with an optional
  // "+" buy bubble beside it when the matching cell has a first-choice link.
  const QtyChip = ({ label, row, materialName, colorId, variant, widthClass = 'w-14' }:
    { label: string; row?: StockRow; materialName: string; colorId: number | null
      variant: string | null; widthClass?: string }) => {
    const level = row?.level ?? 'ok'
    const tip = row && level !== 'ok'
      ? `${LEVEL_LABEL[level]} — now ${row.quantity}`
        + (row.effective_minimum != null ? `, min ${row.effective_minimum}` : '')
        + `, 10-day use ${row.consume_next_10}, future use ${row.consume_future}`
      : 'Tap to filter the movement history by this material'
    return (
      <span className="inline-flex items-center gap-1">
        {/* fixed width (sized for up to 4 digits) + centered, so sibling chips
            match in size and their "+" bubbles line up vertically. Tapping the
            chip filters the movement history by this exact material cell. */}
        <button type="button" title={tip}
          onClick={() => addCellFilter(materialName, colorId, variant)}
          className={`inline-flex ${widthClass} items-center justify-center rounded-full px-2 py-1 text-xs font-bold tabular-nums hover:ring-2 hover:ring-violet-300 ${LEVEL_CHIP[level]}`}>
          {label} {row?.quantity ?? 0}
        </button>
        <BuyPlus link={buyLink(materialName, colorId, variant)} />
      </span>
    )
  }

  // One colour bubble: colour dot on the left, quantities (G/P) on the right.
  // Off-catalogue colours get a dashed border instead of the solid ring.
  const BalloonBubble = ({ code }: { code: string }) => {
    const c = colorByCode.get(code)
    const id = c?.color_id ?? null
    const offCat = c?.in_catalog === false
    return (
      <div className={`flex items-center justify-center gap-2.5 rounded-2xl bg-white p-2.5 shadow-sm ${offCat ? 'border-2 border-dashed border-amber-400' : 'ring-1 ring-violet-100'}`}>
        <div className="flex flex-col items-center gap-0.5">
          <ColorDot big colorId={id} />
          <span className="text-[10px] font-medium text-slate-400">
            {colorName(id) ?? code}{offCat && <span className="text-amber-500"> · off-cat</span>}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <QtyChip label="G" row={cell(GRANDE, id, null)} materialName={GRANDE} colorId={id} variant={null} />
          <QtyChip label="P" row={cell(PICCOLO, id, null)} materialName={PICCOLO} colorId={id} variant={null} />
        </div>
      </div>
    )
  }

  // A neutral (colourless) material: a grey circle with a letter (L long, E helium).
  const NeutralBubble = ({ glyph, caption, materialName }: { glyph: string; caption: string; materialName: string }) => (
    <div className="flex items-center justify-center gap-2.5 rounded-2xl bg-white p-2.5 shadow-sm ring-1 ring-violet-100">
      <div className="flex flex-col items-center gap-0.5">
        <span className="flex h-12 w-12 items-center justify-center rounded-full border border-slate-300 bg-slate-200 text-[13px] font-extrabold text-slate-600">{glyph}</span>
        <span className="text-[10px] font-medium text-slate-400">{caption}</span>
      </div>
      <QtyChip label="Qty" row={cell(materialName, null, null)} materialName={materialName} colorId={null} variant={null} />
    </div>
  )

  // A number: a single colour-filled circle with the digit inside (so it never
  // reads as a colour code, and stays visually distinct from plain balloons).
  const NumberDot = ({ code, digit, big = false }: { code: string; digit: string; big?: boolean }) => {
    const hex = colorByCode.get(code)?.swatch_hex || HEX[code] || '#e5e7eb'
    const sz = big ? 'h-12 w-12 text-lg' : 'h-6 w-6 text-[10px]'
    return (
      <span className={`flex ${sz} shrink-0 items-center justify-center rounded-full border border-slate-300 font-extrabold`}
        style={{ background: hex, color: textOn(hex) }}>{digit}</span>
    )
  }

  // One number card: a colour-filled digit token + the per-size quantity chips.
  const NumberBubble = ({ code, digit }: { code: string; digit: string }) => {
    const id = colorByCode.get(code)?.color_id ?? null
    return (
      <div className="flex items-center justify-center gap-2.5 rounded-2xl bg-white p-2.5 shadow-sm ring-1 ring-violet-100">
        <div className="flex flex-col items-center gap-0.5">
          <NumberDot big code={code} digit={digit} />
          <span className="text-[10px] font-medium text-slate-400">{colorName(id) ?? code}</span>
        </div>
        <div className="flex flex-col gap-1">
          {NUMERO_SIZES.map((s) => (
            <QtyChip key={s.label} label={s.label} row={cell(s.name, id, digit)}
              materialName={s.name} colorId={id} variant={digit} widthClass="w-[4.25rem]" />
          ))}
        </div>
      </div>
    )
  }

  // One compact token for a single sparse number cell (colour + digit + one size).
  const NumberCell = ({ code, digit, sizeName, label }: { code: string; digit: string; sizeName: string; label: string }) => {
    const id = colorByCode.get(code)?.color_id ?? null
    return (
      <div className="inline-flex items-center gap-1.5 rounded-xl bg-white p-1.5 shadow-sm ring-1 ring-violet-100">
        <NumberDot code={code} digit={digit} />
        <QtyChip label={label} row={cell(sizeName, id, digit)}
          materialName={sizeName} colorId={id} variant={digit} widthClass="w-[3.25rem]" />
      </div>
    )
  }

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">📦 Stock</h1>
        {canEdit && (
          <Link to="/inventory_update/new" className="rounded-lg bg-violet-600 px-3 py-2 text-sm font-semibold text-white">
            + Stock Update
          </Link>
        )}
      </div>

      {error && <p className="mb-3 rounded-xl bg-red-50 p-3 text-center text-red-600 shadow ring-1 ring-red-200">{error}</p>}

      {/* 1) FORECAST WARNINGS (red > orange > yellow) -----------------------*/}
      {warnings.length > 0 && (
        <section className="mb-5">
          <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-700">
            <AlertTriangle size={16} className="text-red-500" /> Stock warnings ({warnings.length})
          </h2>
          {/* legend */}
          <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
            {WARN_LEVELS.map((lvl) => warnCount(lvl) > 0 && (
              <span key={lvl} className="inline-flex items-center gap-1">
                <span className={`h-2.5 w-2.5 rounded-full ${LEVEL_DOT[lvl]}`} />
                {LEVEL_LABEL[lvl]} ({warnCount(lvl)})
              </span>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {warnings.map((r, i) => {
              const lvl = r.level as Exclude<WarnLevel, 'ok'>
              return (
                <span key={i} title={`${LEVEL_LABEL[lvl]} — 10-day use ${r.consume_next_10}, future ${r.consume_future}`}
                  className={`rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ${LEVEL_PILL[lvl]}`}>
                  {r.required_item_name}{subLabel(r.color_name, r.variant) ? ` · ${subLabel(r.color_name, r.variant)}` : ''}
                  {' '}<span className="font-bold">{r.quantity}</span>
                  {r.effective_minimum != null && <span className="opacity-60">/{r.effective_minimum}</span>}
                </span>
              )
            })}
          </div>
        </section>
      )}

      {rows.length === 0 && !error && (
        <div className="mb-5 rounded-xl bg-white p-6 text-center text-slate-400 shadow">
          No movements recorded yet.<br />
          <span className="text-sm">Stock will appear after purchases or counts.</span>
        </div>
      )}

      {/* 2a) BALLOONS: G + P per colour -------------------------------------*/}
      <section className="mb-5">
        <h2 className="mb-2 text-sm font-semibold text-slate-600">Balloons <span className="font-normal text-slate-400">— G large · P small</span></h2>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Base</div>
        <AutoGrid min={140} max={210} className="mb-3">
          {BASE_CODES.map((code) => <BalloonBubble key={code} code={code} />)}
        </AutoGrid>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Metallic</div>
        <AutoGrid min={140} max={210}>
          {METAL_CODES.map((code) => <BalloonBubble key={code} code={code} />)}
        </AutoGrid>
        {extraColors.length > 0 && (
          <>
            <div className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Other in stock <span className="font-normal normal-case text-amber-500">— dashed = off-catalogue</span>
            </div>
            <AutoGrid min={140} max={210}>
              {extraColors.map((code) => <BalloonBubble key={code} code={code} />)}
            </AutoGrid>
          </>
        )}
      </section>

      {/* 2b) LONG BALLOONS + HELIUM: neutral -------------------------------*/}
      <section className="mb-5">
        <h2 className="mb-2 text-sm font-semibold text-slate-600">Long balloons &amp; helium <span className="font-normal text-slate-400">— neutral</span></h2>
        <AutoGrid min={140} max={210}>
          <NeutralBubble glyph="L" caption="long" materialName={LUNGO} />
          <NeutralBubble glyph="E" caption="helium" materialName="Elio" />
        </AutoGrid>
      </section>

      {/* 2c) NUMBERS: hot set (digits 1&8, metal) by default; toggle for all --*/}
      <section className="mb-6">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-600">Numbers <span className="font-normal text-slate-400">
            — {showAllNumbers ? 'all digits & colours' : 'digits 1 and 8'} · sizes L·M·S (110/80/35)</span></h2>
          <button type="button" onClick={() => setShowAllNumbers((v) => !v)}
            className="shrink-0 rounded-full border border-violet-200 px-2.5 py-1 text-[11px] font-medium text-violet-600 hover:bg-violet-50">
            {showAllNumbers ? 'Show common only' : 'Show all variants'}
          </button>
        </div>
        {(showAllNumbers ? ALL_NUMERO_DIGITS : NUMERO_DIGITS).map((digit) => (
          <div key={digit} className="mb-3">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Digit {digit}</div>
            <AutoGrid min={160} max={230}>
              {(showAllNumbers ? ALL_NUMERO_CODES : NUMERO_COLOR_CODES).map((code) => (
                <NumberBubble key={code} code={code} digit={digit} />
              ))}
            </AutoGrid>
          </div>
        ))}

        {/* Rare number variants that already hold stock, when not already showing all. */}
        {!showAllNumbers && extraNumberCells.length > 0 && (
          <>
            <div className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Other in stock <span className="font-normal normal-case text-slate-400">— rare variants you own</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {extraNumberCells.map(({ digit, code, sizeName, label }) => (
                <NumberCell key={`${digit}|${code}|${sizeName}`} code={code} digit={digit} sizeName={sizeName} label={label} />
              ))}
            </div>
          </>
        )}
      </section>

      {/* 3) HISTORY ---------------------------------------------------------*/}
      <section ref={historyRef}>
        <h2 className="mb-2 text-sm font-semibold text-slate-600">Movement history</h2>
        {/* category multi-select (toggle any combination) */}
        <div className="mb-2 flex flex-wrap gap-2">
          {HISTORY_TABS.map((t) => {
            const active = cats.has(t.key)
            return (
              <button key={t.key} onClick={() => toggleCat(t.key)}
                className={`rounded-full px-3 py-1.5 text-sm font-medium ${active ? 'bg-violet-600 text-white' : 'bg-white text-slate-600 shadow'}`}>
                {t.label}
              </button>
            )
          })}
        </div>
        {/* material filters picked from the stock chips above */}
        {cellFilters.length > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            {cellFilters.map((f) => (
              <span key={f.key}
                className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2.5 py-1 text-[11px] font-medium text-violet-700">
                {f.label}
                <button onClick={() => removeCellFilter(f.key)} aria-label="remove filter"
                  className="text-violet-500 hover:text-violet-900">✕</button>
              </span>
            ))}
            <button onClick={() => setCellFilters([])} className="text-[11px] text-slate-400 underline">
              clear
            </button>
          </div>
        )}

        {historyByDate.length === 0 ? (
          <p className="rounded-xl bg-white p-4 text-center text-sm text-slate-400 shadow">No movements for this filter.</p>
        ) : (
          <div className="space-y-4">
            {historyByDate.map(([date, byType]) => (
              <section key={date} className="overflow-hidden rounded-xl bg-white shadow">
                {/* DATE band */}
                <div className="bg-gradient-to-r from-violet-500 to-sky-400 px-3 py-2">
                  <span className="rounded-full bg-white/25 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-white">
                    {formatDate(date)}
                  </span>
                </div>

                <div className="space-y-2 p-2">
                  {byType.map(([type, updates]) => {
                    const meta = TYPE_META[type] ?? { label: type, Icon: Scale, tint: 'text-slate-600' }
                    const Icon = meta.Icon
                    return (
                      <div key={type} className="overflow-hidden rounded-lg border border-violet-100">
                        {/* TYPE band */}
                        <div className="flex items-center gap-1 bg-violet-100 px-2.5 py-1.5">
                          <Icon size={13} className="shrink-0 text-violet-500" />
                          <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs font-semibold text-violet-800">{meta.label}</span>
                        </div>

                        <div className="space-y-1.5 bg-violet-50/40 p-1.5">
                          {updates.map((u) => {
                            const oh = orderHeader(u)
                            // When material filters are active, show only the matching
                            // lines of each movement, not the whole update.
                            const shownItems = cellFilters.length ? u.items.filter(matchItem) : u.items
                            // Numbers get their own colour-filled digit token; other
                            // materials are grouped by colour (code dot + abbrevs).
                            const numItems = shownItems.filter((it) => riName(it.required_item_id).startsWith('Palloncino numero'))
                            const neutralItems = shownItems.filter((it) => NEUTRAL_GLYPH[riName(it.required_item_id)])
                            const groups = new Map<number | null, UpdateItem[]>()
                            for (const it of shownItems) {
                              const n = riName(it.required_item_id)
                              if (n.startsWith('Palloncino numero') || NEUTRAL_GLYPH[n]) continue
                              const arr = groups.get(it.color_id) ?? []
                              arr.push(it); groups.set(it.color_id, arr)
                            }
                            const colorGroups = [...groups.entries()]
                              .sort((a, b) => (colorName(a[0]) || '~').localeCompare(colorName(b[0]) || '~'))
                            return (
                              <div key={u.inventory_update_id}
                                onClick={() => navigate(`/inventory_update/${u.inventory_update_id}`)}
                                className="cursor-pointer rounded-md bg-white p-2 shadow-sm hover:bg-violet-50">
                                <div className="flex items-start justify-between gap-2">
                                  {oh ? (
                                    <span className="flex min-w-0 flex-1 items-center gap-1 text-xs">
                                      <MapPin size={12} className="shrink-0 text-violet-400" />
                                      <span className="truncate">
                                        <span className="font-semibold text-slate-700">{oh.loc}</span>
                                        {oh.comps && <span className="text-slate-400"> · {oh.comps}</span>}
                                      </span>
                                    </span>
                                  ) : refillSupplier(u) ? (
                                    <span className="flex min-w-0 flex-1 items-center gap-1 text-xs">
                                      <Store size={12} className="shrink-0 text-violet-400" />
                                      <span className="truncate font-semibold text-slate-700">{refillSupplier(u)}</span>
                                    </span>
                                  ) : u.comment ? (
                                    <span className="min-w-0 flex-1 truncate text-xs text-slate-500">{u.comment}</span>
                                  ) : <span className="flex-1" />}
                                  <ChevronRight size={15} className="mt-0.5 shrink-0 text-slate-300" />
                                </div>
                                <div className="mt-1.5 flex flex-wrap gap-1.5">
                                  {colorGroups.map(([cid, its]) => (
                                    <span key={String(cid)}
                                      className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-full bg-slate-50 py-0.5 pl-0.5 pr-2 ring-1 ring-slate-200">
                                      <ColorDot colorId={cid} />
                                      {its.map((it, i) => (
                                        <span key={i} className="text-[11px] text-slate-500">
                                          {riAbbr(it.required_item_id)}
                                          <b className={`ml-0.5 tabular-nums ${meta.tint}`}>
                                            {fmtChange(type, u, it)}
                                          </b>
                                        </span>
                                      ))}
                                    </span>
                                  ))}
                                  {numItems.map((it, i) => (
                                    <span key={`n${i}`}
                                      className="inline-flex items-center gap-1 rounded-full bg-slate-50 py-0.5 pl-0.5 pr-2 ring-1 ring-slate-200">
                                      <NumberDot code={color(it.color_id)?.code ?? ''} digit={it.variant ?? 'N'} />
                                      <span className="text-[11px] text-slate-500">
                                        {riName(it.required_item_id).replace('Palloncino numero ', '')}
                                        <b className={`ml-0.5 tabular-nums ${meta.tint}`}>
                                          {fmtChange(type, u, it)}
                                        </b>
                                      </span>
                                    </span>
                                  ))}
                                  {neutralItems.map((it, i) => (
                                    <span key={`x${i}`}
                                      className="inline-flex items-center gap-1 rounded-full bg-slate-50 py-0.5 pl-0.5 pr-2 ring-1 ring-slate-200">
                                      <span className="flex h-6 w-6 items-center justify-center rounded-full border border-slate-300 bg-slate-200 text-[10px] font-extrabold text-slate-600">
                                        {NEUTRAL_GLYPH[riName(it.required_item_id)]}
                                      </span>
                                      <b className={`text-[11px] tabular-nums ${meta.tint}`}>
                                        {fmtChange(type, u, it)}
                                      </b>
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}