import { Children, useLayoutEffect, useRef, useState, type ReactNode } from 'react'

// Responsive bubble/card grid: fits as many columns as possible with each cell
// between `min` and `max` px, then stretches them (1fr) to fill the row exactly
// (no ragged right edge). Wider screen => more cells per row; narrower => fewer
// but never below `min`. Columns are capped at the child count so a short row
// doesn't leave empty tracks.
export default function AutoGrid({ min, max, gap = 8, className = '', children }:
  { min: number; max: number; gap?: number; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const count = Children.count(children)
  const [cols, setCols] = useState(2)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const compute = () => {
      const w = el.clientWidth
      if (w <= 0) return
      const maxCols = Math.max(1, Math.floor((w + gap) / (min + gap)))  // each >= min
      const minCols = Math.max(1, Math.ceil((w + gap) / (max + gap)))   // each <= max
      setCols(Math.max(1, Math.min(Math.min(minCols, maxCols), count || 1)))
    }
    compute()
    const ro = new ResizeObserver(compute)
    ro.observe(el)
    return () => ro.disconnect()
  }, [min, max, gap, count])
  return (
    <div ref={ref} className={className}
      style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: `${gap}px` }}>
      {children}
    </div>
  )
}
