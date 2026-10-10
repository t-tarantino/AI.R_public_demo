import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react'
import { api } from '../api'
import { BASE_CODES, hexFor, METAL_CODES, textOn } from '../lib/colors'
import { useCanEdit } from '../lib/user'
import AutoGrid from '../components/AutoGrid'

// Two-level browse. Main screen: balloons shown as a colour palette (macro
// areas Base/Metallic) where each colour carries G (large) and P (small)
// buttons — pick a colour+size directly; other materials as tiles. Selecting
// anything opens the matching PRODUCTS (what we buy), filtered accordingly.

interface Product {
  product_id: number; required_item_id: number; color_id: number | null
  product_code: string | null; product_link: string | null
  name: string; package_quantity: number; active: boolean
  variant: string | null; is_first_choice: boolean
}
interface Material {
  required_item_id: number; name: string
  type: string | null; dimension: string | null; used_color: boolean
}
interface Color { color_id: number; code: string; name: string; in_catalog: boolean; swatch_hex?: string | null }

const GRANDE = 'Palloncino grande'
const PICCOLO = 'Palloncino piccolo'
const TYPE_LABEL: Record<string, string> = {
  balloon: 'Balloons', gas: 'Gas', curtain: 'Curtains', structure: 'Structures', other: 'Other',
}
const TYPE_ORDER = ['balloon', 'gas', 'curtain', 'structure', 'other']

type Selection = { materialId: number; colorId: number | null }

function ColorDot({ color, size = 'md' }: { color?: Color; size?: 'sm' | 'md' | 'lg' }) {
  const hex = color?.swatch_hex || (color ? hexFor(color.code) : '#e2e8f0')
  const cls = size === 'lg' ? 'h-14 w-14 text-sm' : size === 'md' ? 'h-8 w-8 text-[9px]' : 'h-5 w-5 text-[7px]'
  return (
    <span className={`flex ${cls} shrink-0 items-center justify-center rounded-full border border-slate-300 font-bold`}
      style={{ background: hex, color: textOn(hex) }} title={color?.name ?? 'neutral'}>
      {color?.code ?? '—'}
    </span>
  )
}

export default function ProductList() {
  const navigate = useNavigate()
  const canEdit = useCanEdit()
  const [products, setProducts] = useState<Product[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [colors, setColors] = useState<Color[]>([])
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Selection | null>(null)

  useEffect(() => {
    Promise.all([
      api.get<Product[]>('/api/product'),
      api.get<Material[]>('/api/required_item'),
      api.get<Color[]>('/api/color'),
    ]).then(([p, m, c]) => { setProducts(p); setMaterials(m); setColors(c) })
      .catch((e) => setError(e.message))
  }, [])

  const colorById = useMemo(() => Object.fromEntries(colors.map((c) => [c.color_id, c])) as Record<number, Color>, [colors])
  const colorByCode = useMemo(() => new Map(colors.map((c) => [c.code, c])), [colors])
  const matByName = useMemo(() => Object.fromEntries(materials.map((m) => [m.name, m])) as Record<string, Material>, [materials])
  const grande = matByName[GRANDE]
  const piccolo = matByName[PICCOLO]

  const productsByMaterial = useMemo(() => {
    const m = new Map<number, Product[]>()
    for (const p of products) { const l = m.get(p.required_item_id) ?? []; l.push(p); m.set(p.required_item_id, l) }
    return m
  }, [products])
  const countFor = (materialId: number | undefined, colorId: number) =>
    materialId === undefined ? 0 : products.filter((p) => p.required_item_id === materialId && p.color_id === colorId).length

  // Balloon colours present in products beyond the curated palette (off-catalogue).
  const extraCodes = useMemo(() => {
    const palette = new Set([...BASE_CODES, ...METAL_CODES])
    const codes = new Set<string>()
    for (const p of products) {
      if ((p.required_item_id === grande?.required_item_id || p.required_item_id === piccolo?.required_item_id) && p.color_id) {
        const code = colorById[p.color_id]?.code
        if (code && !palette.has(code)) codes.add(code)
      }
    }
    return [...codes].sort()
  }, [products, colorById, grande, piccolo])

  // Materials other than the two balloon-palette ones, grouped by type (tiles).
  const otherByType = useMemo(() => {
    const g = new Map<string, Material[]>()
    for (const m of [...materials].sort((a, b) =>
      (a.dimension ?? '').localeCompare(b.dimension ?? '') || a.name.localeCompare(b.name))) {
      if (m.name === GRANDE || m.name === PICCOLO) continue
      const t = m.type || 'other'
      const l = g.get(t) ?? []; l.push(m); g.set(t, l)
    }
    return [...g.entries()].sort((a, b) => {
      const ia = TYPE_ORDER.indexOf(a[0]), ib = TYPE_ORDER.indexOf(b[0])
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
    })
  }, [materials])

  const materialColors = (materialId: number): Color[] => {
    const ids = new Set<number>()
    for (const p of productsByMaterial.get(materialId) ?? []) if (p.color_id) ids.add(p.color_id)
    return [...ids].map((id) => colorById[id]).filter(Boolean).sort((a, b) => a.name.localeCompare(b.name))
  }

  // ---------- DETAIL: products for a material (optionally one colour) ----------
  if (selected !== null) {
    const material = materials.find((m) => m.required_item_id === selected.materialId)
    const selColor = selected.colorId !== null ? colorById[selected.colorId] : undefined
    let prods = (productsByMaterial.get(selected.materialId) ?? []).slice()
    if (selected.colorId !== null) prods = prods.filter((p) => p.color_id === selected.colorId)
    prods.sort((a, b) =>
      (colorById[a.color_id ?? -1]?.name ?? '~').localeCompare(colorById[b.color_id ?? -1]?.name ?? '~')
      || a.name.localeCompare(b.name))
    // group by colour only when not already filtered to one colour
    const groups = new Map<number | 'none', Product[]>()
    for (const p of prods) { const k = p.color_id ?? 'none'; const l = groups.get(k) ?? []; l.push(p); groups.set(k, l) }
    const showColorGroups = selected.colorId === null && material?.used_color

    return (
      <div className="p-3">
        <button onClick={() => setSelected(null)} className="mb-3 flex items-center gap-1 text-sm font-medium text-violet-600">
          <ChevronLeft size={16} /> Materials
        </button>
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            {selColor && <ColorDot color={selColor} size="md" />}
            <h1 className="truncate text-xl font-bold">
              {material?.name}
              {material?.dimension && <span className="ml-2 text-base font-normal text-slate-400">{material.dimension}</span>}
              {selColor && <span className="ml-2 text-base font-normal text-slate-500">· {selColor.name}</span>}
            </h1>
          </div>
          {canEdit && <Link to="/e/product/new" className="shrink-0 rounded-lg bg-violet-600 px-3 py-2 text-sm font-semibold text-white">+ New</Link>}
        </div>

        {prods.length === 0 ? (
          <p className="rounded-xl bg-white p-6 text-center text-slate-400 shadow">No products here yet.</p>
        ) : (
          <div className="overflow-hidden rounded-xl bg-white shadow">
            {[...groups.entries()].map(([key, ps]) => (
              <div key={String(key)} className="border-b border-slate-100 last:border-0">
                {showColorGroups && (
                  <div className="flex items-center gap-2 bg-slate-50 px-3 py-1.5">
                    <ColorDot color={key === 'none' ? undefined : colorById[key as number]} size="sm" />
                    <span className="text-sm font-semibold text-slate-600">
                      {key === 'none' ? '— no colour —' : (colorById[key as number]?.name ?? `#${key}`)}
                    </span>
                  </div>
                )}
                {ps.map((p) => (
                  <div key={p.product_id} onClick={() => navigate(`/e/product/${p.product_id}`)}
                    className={`flex cursor-pointer items-center gap-2 px-3 py-2.5 hover:bg-violet-50 ${p.active ? '' : 'opacity-40'}`}>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        {p.is_first_choice && <span title="First choice — opens from the Stock + button" className="shrink-0 text-amber-500">⭐</span>}
                        <span className="truncate text-sm font-medium">{p.name}</span>
                        {p.variant && <span className="shrink-0 rounded bg-slate-100 px-1.5 text-[10px] font-bold text-slate-500">#{p.variant}</span>}
                      </div>
                      {p.product_code && <div className="font-mono text-[11px] text-slate-400">{p.product_code}</div>}
                    </div>
                    {p.package_quantity > 1 && <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">×{p.package_quantity}/conf</span>}
                    {p.product_link && <a href={p.product_link} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="shrink-0 text-slate-400 hover:text-violet-600"><ExternalLink size={15} /></a>}
                    {!p.active && <span className="shrink-0 text-[11px] text-slate-400">inactive</span>}
                    <ChevronRight size={15} className="shrink-0 text-slate-300" />
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // ---------- MENU --------------------------------------------------------------
  // A balloon colour card: big swatch + G/P buttons that open that colour+size.
  const BalloonCard = ({ code }: { code: string }) => {
    const c = colorByCode.get(code)
    if (!c) return null
    const offCat = c.in_catalog === false
    const gN = countFor(grande?.required_item_id, c.color_id)
    const pN = countFor(piccolo?.required_item_id, c.color_id)
    const Btn = ({ label, n, materialId }: { label: string; n: number; materialId?: number }) => (
      <button disabled={materialId === undefined}
        onClick={() => materialId !== undefined && setSelected({ materialId, colorId: c.color_id })}
        className={`rounded-lg px-2.5 py-1 text-xs font-bold ${n ? 'bg-violet-100 text-violet-700' : 'bg-slate-100 text-slate-400'}`}>
        {label}<span className="ml-1 font-normal">{n}</span>
      </button>
    )
    return (
      <div className={`flex flex-col items-center gap-1.5 rounded-2xl bg-white p-2.5 shadow-sm ${offCat ? 'border-2 border-dashed border-amber-400' : 'ring-1 ring-violet-100'}`}>
        <ColorDot color={c} size="lg" />
        <span className="text-center text-[11px] font-medium text-slate-500">{c.name}{offCat && <span className="text-amber-500"> ·off</span>}</span>
        <div className="flex gap-1">
          <Btn label="G" n={gN} materialId={grande?.required_item_id} />
          <Btn label="P" n={pN} materialId={piccolo?.required_item_id} />
        </div>
      </div>
    )
  }

  return (
    <div className="p-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h1 className="text-xl font-bold">Products (SKU)</h1>
        {canEdit && <Link to="/e/product/new" className="rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white">+ New</Link>}
      </div>
      <p className="mb-4 text-sm text-slate-500">Pick a colour & size (G large · P small), or a material below.</p>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      {/* Balloons: colour palette with G/P buttons */}
      <section className="mb-6">
        <h2 className="mb-2 text-xs font-bold uppercase tracking-wide text-violet-500">Balloons — by colour</h2>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Base</div>
        <AutoGrid min={100} max={150} className="mb-3">{BASE_CODES.map((code) => <BalloonCard key={code} code={code} />)}</AutoGrid>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Metallic</div>
        <AutoGrid min={100} max={150}>{METAL_CODES.map((code) => <BalloonCard key={code} code={code} />)}</AutoGrid>
        {extraCodes.length > 0 && (
          <>
            <div className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Other <span className="font-normal normal-case text-amber-500">— dashed = off-catalogue</span></div>
            <AutoGrid min={100} max={150}>{extraCodes.map((code) => <BalloonCard key={code} code={code} />)}</AutoGrid>
          </>
        )}
      </section>

      {/* Other materials as tiles */}
      {otherByType.map(([type, mats]) => (
        <section key={type} className="mb-5">
          <h2 className="mb-2 text-xs font-bold uppercase tracking-wide text-violet-500">{TYPE_LABEL[type] ?? type}</h2>
          <div className="space-y-2">
            {mats.map((m) => {
              const count = (productsByMaterial.get(m.required_item_id) ?? []).length
              const mcolors = m.used_color ? materialColors(m.required_item_id) : []
              return (
                <div key={m.required_item_id} onClick={() => setSelected({ materialId: m.required_item_id, colorId: null })}
                  className="cursor-pointer rounded-xl bg-white p-3 shadow hover:bg-violet-50">
                  <div className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <span className="font-semibold">{m.name}</span>
                      {m.dimension && <span className="ml-2 text-sm text-slate-400">{m.dimension}</span>}
                    </div>
                    <span className="shrink-0 text-[11px] text-slate-400">{count} {count === 1 ? 'product' : 'products'}</span>
                    <ChevronRight size={16} className="shrink-0 text-slate-300" />
                  </div>
                  {mcolors.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">{mcolors.map((c) => <ColorDot key={c.color_id} color={c} size="sm" />)}</div>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}
