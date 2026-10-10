// Config-driven CRUD: each entity describes its API endpoint, primary key,
// list columns and form fields. The generic EntityList / EntityForm screens
// render everything from this table.

export type FieldType = 'text' | 'textarea' | 'decimal' | 'int' | 'bool' | 'fk' | 'color'

export interface FieldDef {
  name: string
  label: string
  type: FieldType
  required?: boolean
  // for fk fields: which entity provides the options and how to label them
  fkEntity?: string
  fkLabel?: (r: Record<string, unknown>) => string
  placeholder?: string
  help?: string
  default?: unknown      // value pre-filled on a NEW record
}

export interface EntityDef {
  key: string            // URL segment of the API:  /api/{key}
  pk: string
  title: string          // plural, for menus and list header
  titleOne: string       // singular, for form header
  description?: string   // optional help shown under the list header
  listColumns: { name: string; label: string }[]
  fields: FieldDef[]
  hasActive: boolean     // supports deactivate
  hasDelete?: boolean    // supports hard delete (with a server-side guard)
  searchable: boolean
}

const label = (r: Record<string, unknown>, ...keys: string[]) =>
  keys.map((k) => r[k]).filter(Boolean).join(' — ')

export const ENTITIES: EntityDef[] = [
  {
    key: 'composition', pk: 'composition_id', title: 'Price list / Compositions',
    titleOne: 'Composition', hasActive: true, searchable: true,
    listColumns: [
      { name: 'code', label: 'Code' },
      { name: 'name', label: 'Name' },
      { name: 'standard_price', label: '€' },
    ],
    fields: [
      { name: 'code', label: 'Code', type: 'text', required: true },
      { name: 'name', label: 'Name', type: 'text', required: true },
      { name: 'standard_price', label: 'Standard price (€)', type: 'decimal', required: true },
      { name: 'estimated_working_time', label: 'Estimated time (minutes)', type: 'int' },
      { name: 'active', label: 'Active', type: 'bool' },
      { name: 'comment', label: 'Notes', type: 'textarea' },
    ],
  },
  {
    key: 'color', pk: 'color_id', title: 'Colors', titleOne: 'Color',
    hasActive: true, searchable: true,
    listColumns: [
      { name: 'code', label: 'Code' },
      { name: 'name', label: 'Name' },
    ],
    fields: [
      { name: 'code', label: 'Code', type: 'text', required: true },
      { name: 'name', label: 'Name', type: 'text', required: true },
      { name: 'type', label: 'Type (normal/metal/…)', type: 'text' },
      { name: 'swatch_hex', label: 'Colore sfondo (bolla)', type: 'color' },
      { name: 'active', label: 'Active', type: 'bool' },
      { name: 'comment', label: 'Notes', type: 'textarea' },
    ],
  },
  {
    key: 'party', pk: 'party_id', title: 'Parties', titleOne: 'Party',
    hasActive: false, searchable: true,
    listColumns: [
      { name: 'code_nickname', label: 'Code' },
      { name: 'name', label: 'Name' },
      { name: 'category', label: 'Category' },
    ],
    fields: [
      { name: 'name', label: 'Name', type: 'text', required: true },
      { name: 'code_nickname', label: 'Code (e.g. AMZ)', type: 'text' },
      { name: 'is_customer', label: 'Is customer', type: 'bool' },
      { name: 'is_supplier', label: 'Is supplier', type: 'bool' },
      { name: 'is_worker', label: 'Is worker', type: 'bool' },
      { name: 'credit_hours', label: 'Credit hours (Time ranking only)', type: 'decimal' },
      { name: 'hidden_from_ranking', label: 'Hide from Time ranking', type: 'bool' },
      { name: 'is_business', label: 'Is business', type: 'bool' },
      { name: 'category', label: 'Category (online/shop…)', type: 'text' },
      { name: 'phone', label: 'Phone', type: 'text' },
      { name: 'email', label: 'Email', type: 'text' },
      { name: 'website', label: 'Website', type: 'text' },
      { name: 'comment', label: 'Notes', type: 'textarea' },
    ],
  },
  {
    key: 'location', pk: 'location_id', title: 'Locations', titleOne: 'Location',
    hasActive: false, searchable: true,
    listColumns: [
      { name: 'name', label: 'Name' },
      { name: 'address', label: 'Address' },
    ],
    fields: [
      { name: 'name', label: 'Name', type: 'text', required: true },
      { name: 'address', label: 'Address', type: 'text' },
      { name: 'phone', label: 'Phone', type: 'text' },
      { name: 'email', label: 'Email', type: 'text' },
      { name: 'comment', label: 'Notes', type: 'textarea' },
    ],
  },
  {
    key: 'required_item', pk: 'required_item_id', title: 'Materials',
    titleOne: 'Material', hasActive: false, searchable: true,
    listColumns: [
      { name: 'name', label: 'Name' },
      { name: 'unit', label: 'Unit' },
      { name: 'minimum_safe_quantity', label: 'Min. stock' },
    ],
    fields: [
      { name: 'name', label: 'Name', type: 'text', required: true },
      { name: 'type', label: 'Type (balloon/gas/…)', type: 'text' },
      { name: 'dimension', label: 'Dimension (e.g. 30cm)', type: 'text' },
      { name: 'unit', label: 'Unit (piece/kg/lt/mt)', type: 'text', required: true },
      { name: 'used_color', label: 'Uses colors', type: 'bool' },
      { name: 'minimum_safe_quantity', label: 'Default minimum stock', type: 'int' },
      { name: 'comment', label: 'Notes', type: 'textarea' },
    ],
  },
  {
    key: 'product', pk: 'product_id', title: 'Products (SKU)', titleOne: 'Product',
    hasActive: true, searchable: true,
    listColumns: [
      { name: 'name', label: 'Name' },
      { name: 'product_code', label: 'Code' },
      { name: 'default_price', label: '€' },
    ],
    fields: [
      { name: 'name', label: 'Name', type: 'text', required: true },
      {
        name: 'required_item_id', label: 'Required item', type: 'fk',
        required: true, fkEntity: 'required_item',
        fkLabel: (r) => label(r, 'name', 'dimension'),
      },
      {
        name: 'color_id', label: 'Color', type: 'fk', fkEntity: 'color',
        fkLabel: (r) => label(r, 'code', 'name'),
      },
      {
        name: 'variant', label: 'Digit (numbers only)', type: 'text',
        placeholder: 'e.g. 1 or 8 — leave empty otherwise',
        help: 'Only for foil numbers: the digit this SKU is for. Leave empty for everything else.',
      },
      { name: 'product_code', label: 'Product code', type: 'text' },
      {
        name: 'package_quantity', label: 'Pieces per pack', type: 'int', required: true, default: 1,
        help: 'Pieces per purchased unit (pack size). Buying 2 packs of 100 adds 200 to stock. '
          + 'Use 1 if sold per piece.',
      },
      {
        name: 'default_price', label: 'Default price (€ per pack)', type: 'decimal',
        help: 'Usual cost per purchased unit (pack). Pre-fills the cost when adding an '
          + 'expense for this product; if the entered cost differs you get a warning. '
          + 'Leave empty if the price varies too much.',
      },
      { name: 'product_link', label: 'Purchase link (Amazon / Festival…)', type: 'text' },
      {
        name: 'is_first_choice', label: 'First choice (Stock "+" buy button)', type: 'bool',
        help: 'The preferred product to reorder for this material+colour+digit. Turning it on '
          + 'automatically turns it off on the other products of the same cell.',
      },
      { name: 'active', label: 'Active', type: 'bool' },
      { name: 'comment', label: 'Notes', type: 'textarea' },
    ],
  },
  {
    key: 'stock_threshold', pk: 'stock_threshold_id', title: 'Stock thresholds',
    titleOne: 'Stock threshold', hasActive: false, searchable: false,
    description: 'Per-colour / per-digit EXCEPTIONS to the reorder minimum. '
      + 'The base minimum of a material (used for every colour without an exception here) '
      + 'lives on the material itself, under Materials → “Default minimum stock”. '
      + 'A row with empty colour/digit means “any”.',
    listColumns: [
      { name: 'required_item_id', label: 'Material' },
      { name: 'color_id', label: 'Color' },
      { name: 'variant', label: 'Digit' },
      { name: 'minimum_quantity', label: 'Min' },
    ],
    fields: [
      {
        name: 'required_item_id', label: 'Material', type: 'fk', required: true,
        fkEntity: 'required_item', fkLabel: (r) => label(r, 'name', 'dimension'),
      },
      {
        name: 'color_id', label: 'Color (empty = any)', type: 'fk',
        fkEntity: 'color', fkLabel: (r) => label(r, 'code', 'name'),
      },
      {
        name: 'variant', label: 'Digit (empty = any)', type: 'text',
        help: 'Only for foil numbers: the digit (0–9) this exception is for. Leave empty otherwise.',
      },
      { name: 'minimum_quantity', label: 'Minimum quantity', type: 'int', required: true },
      { name: 'comment', label: 'Notes', type: 'textarea' },
    ],
  },
  {
    key: 'expense_category', pk: 'expense_category_id', title: 'Expense categories',
    titleOne: 'Expense category', hasActive: false, hasDelete: true, searchable: true,
    listColumns: [{ name: 'name', label: 'Name' }],
    fields: [{ name: 'name', label: 'Name', type: 'text', required: true }],
  },
]

export const entityByKey = (key: string): EntityDef => {
  const def = ENTITIES.find((e) => e.key === key)
  if (!def) throw new Error(`Unknown entity: ${key}`)
  return def
}
