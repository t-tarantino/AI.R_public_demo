// Swatch colour per catalogue code (+ known off-catalogue codes). Shared by the
// Stock and Products screens so the palette stays consistent.
export const HEX: Record<string, string> = {
  '001': '#f3f4f6', '014': '#1f2937', '068': '#14b8a6', '009': '#7dd3fc',
  '010': '#2743a3', '079': '#c4a3d9', '006': '#ec9cbb', '007': '#d6337f',
  '045': '#d92534', '013': '#3ba14f', '008': '#6b3fa0', '004': '#e8892a',
  '002': '#f5c51a', '089': '#c0c4c8', '096': '#c08a72', '054': '#1f4fb0',
  '064': '#c31e6d', '088': '#c8a227', '028': '#eae2d2',
  '101': '#6e1a2e', '102': '#16264d',
}

// Readable text over a swatch (dark on light colours, else white).
export const textOn = (hex: string) => {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16)
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? '#334155' : '#ffffff'
}

export const hexFor = (code: string | undefined | null) => (code ? HEX[code] ?? '#e5e7eb' : '#e2e8f0')

// Curated balloon palette, split into the two macro areas used across the app.
export const BASE_CODES = ['001', '014', '068', '009', '010', '079', '006', '007', '045', '013', '008', '004', '002']
export const METAL_CODES = ['089', '096', '054', '064', '088', '028']
