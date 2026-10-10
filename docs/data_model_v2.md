# AI.R Internal System — Data Model **v2** (design spec)

Status: **proposal / not yet implemented.** v1 (currently in the database) stays
as-is until we decide to migrate. This document specifies the redesigned schema
agreed in the design discussion. Implementation (ORM models, Alembic migration,
updated `master_data.toml`/importer) is a separate later step.

## What changed at a glance (v1 → v2)
1. **`party`** unifies `customer` + `supplier` + `worker` into one anagraphic
   table with role flags. The separate `worker` table is **removed**.
2. **Bill of materials**: new `required_item` + `requirements` tables replace the
   provisional `estimated_*_balloons` fields on `composition`.
3. **Inventory is tracked at `required_item` level**, not per product.
4. **`product`** becomes a concrete purchasable SKU (code + link) that satisfies
   a `required_item` in a color; `brand`/`package_quantity` dropped.
5. **`customer_order`** (renamed from `orders`) gains `state`, `event_type`,
   `celebrated_age`, `celebrant_gender`, and an optional `customer_party_id`.
6. **`expense`** records a money flow `paid_by_party` → `paid_to_party`; expense
   lines carry a controlled `expense_category`.
7. **`work`** tracks time (start/end timestamps + break) and activity only — no
   wage. Worker pay is recorded as `expense` (profit split), so it is already a
   correct historical fact.

Legend: 🟦 master/current-value · 🟧 historical/transactional · 🟩 configuration (BOM).
Types: money = `NUMERIC(10,2)`; percentage = `NUMERIC(5,2)` (0–100);
enum = `VARCHAR` + CHECK or lookup table; ids = integer surrogate `<entity>_id`.

---

## 🟦 Master tables

### party  *(replaces customer + supplier + worker)*
| Column | Type | Null | Notes |
|---|---|---|---|
| party_id | int PK | no | |
| name | varchar | no | |
| code_nickname | varchar UNIQUE | yes | e.g. AMZ, FMG, CNA, CJM — finally has a home |
| is_customer | bool | no | default false |
| is_supplier | bool | no | default false |
| is_worker | bool | no | default false |
| category | varchar | yes | supplier grouping, e.g. "online" / "negozio fisico" |
| phone | varchar | yes | |
| email | varchar | yes | |
| website | varchar | yes | |
| comment | text | yes | |

- Role flags allow **multi-role** (a party can be supplier *and* customer; the
  business itself is a party that both pays and gets paid).
- Constraint: at least one role flag true (CHECK).

### location
| Column | Type | Null | Notes |
|---|---|---|---|
| location_id | int PK | no | |
| name | varchar | no | |
| address | varchar | yes | |
| phone | varchar | yes | new in v2 |
| email | varchar | yes | new in v2 |
| comment | text | yes | |

### color
| Column | Type | Null | Notes |
|---|---|---|---|
| color_id | int PK | no | |
| code | varchar UNIQUE | no | |
| name | varchar | no | |
| type | varchar | yes | new: e.g. normale / metal / perla |
| active | bool | no | default true |
| in_catalog | bool | no | default true; false = off-catalog colour (adds a surcharge on use). Orthogonal to `active`. |
| comment | text | yes | |

### composition
| Column | Type | Null | Notes |
|---|---|---|---|
| composition_id | int PK | no | |
| code | varchar UNIQUE | no | TEXT (001, 05S, P01, NME, 012E…) |
| name | varchar | no | |
| standard_price | numeric(10,2) | no | current/default price |
| estimated_working_time | int | yes | minutes |
| active | bool | no | default true |
| comment | text | yes | |

- `estimated_large/small_balloons` **removed** → now expressed via `requirements`.

### expense_category  *(controlled vocabulary — the "elenco fisso")*
| Column | Type | Null | Notes |
|---|---|---|---|
| expense_category_id | int PK | no | |
| name | varchar UNIQUE | no | materials, transport, fuel, … |

---

## 🟩 Bill of materials (configuration)

### required_item  *(what a composition needs — abstract)*
| Column | Type | Null | Notes |
|---|---|---|---|
| required_item_id | int PK | no | |
| name | varchar | no | e.g. "Palloncino grande", "Nastro" |
| type | varchar | yes | category of material |
| dimension | varchar | yes | e.g. "30cm" |
| unit | varchar | no | piece / kg / lt / … |
| used_color | bool | no | default false — does this item have a color? |
| minimum_safe_quantity | int | yes | reorder threshold (stock lives here) |
| comment | text | yes | |

### requirements  *(composition ↔ required_item, with quantity)*
| Column | Type | Null | Notes |
|---|---|---|---|
| requirement_id | int PK | no | |
| composition_id | int FK→composition | no | |
| required_item_id | int FK→required_item | no | |
| quantity | numeric(10,2) | no | how much of the item the composition needs |
| comment | text | yes | |

- UNIQUE `(composition_id, required_item_id)`.
- Cardinality: one composition → many requirements; one required_item → many.

### product  *(concrete purchasable SKU)*
| Column | Type | Null | Notes |
|---|---|---|---|
| product_id | int PK | no | |
| required_item_id | int FK→required_item | no | which need it satisfies |
| color_id | int FK→color | yes | |
| product_code | varchar | yes | |
| product_link | varchar | yes | purchase URL |
| name | varchar | no | |
| active | bool | no | default true |
| comment | text | yes | |

- Several products (different sources) can satisfy the **same** required_item.
- `brand` and `package_quantity` intentionally **dropped** (the link + source
  identify the purchase; pack size not needed).

---

## 🟧 Historical / transactional tables

### customer_order  *(renamed from `orders`; avoids the reserved word too)*
| Column | Type | Null | Notes |
|---|---|---|---|
| customer_order_id | int PK | no | |
| location_id | int FK→location | no | |
| customer_party_id | int FK→party | yes | usually null (= location); ready for the future |
| state | varchar | no | enum: draft / confirmed / completed / cancelled |
| event_type | varchar | yes | enum (compleanno, matrimonio, …) — list TBD |
| celebrated_age | int | yes | |
| celebrant_gender | varchar | yes | enum M / F / altro |
| date | date | no | |
| total_price | numeric(10,2) | no | actual customer-facing total |
| comment | text | yes | |

### order_item
| Column | Type | Null | Notes |
|---|---|---|---|
| order_item_id | int PK | no | |
| customer_order_id | int FK→customer_order | no | |
| composition_id | int FK→composition | no | |
| quantity | int | no | > 0 |
| unit_price | numeric(10,2) | no | **historical snapshot** |
| discount | numeric(5,2) | yes | 0–100 |
| comment | text | yes | |

### order_item_color
| Column | Type | Null | Notes |
|---|---|---|---|
| order_item_color_id | int PK | no | |
| order_item_id | int FK→order_item | no | |
| color_id | int FK→color | no | |
| color_percentage | numeric(5,2) | yes | 0–100 |
| color_surcharge | numeric(10,2) | no | default 0; historical surcharge € for this colour on this line (>0 typically when `color.in_catalog=false`). CHECK ≥ 0. |
| comment | text | yes | |

- UNIQUE `(order_item_id, color_id)`.
- Colour surcharge lives here (not on `order_item`): it is caused by the chosen colour. Total surcharge revenue = `SUM(color_surcharge)`; `order_item.unit_price` stays the base list price.

### expense
| Column | Type | Null | Notes |
|---|---|---|---|
| expense_id | int PK | no | |
| paid_by_party_id | int FK→party | no | who paid |
| paid_to_party_id | int FK→party | no | who was paid |
| date | date | no | |
| total_cost | numeric(10,2) | no | actual total paid |
| payment_method | varchar | yes | |
| comment | text | yes | |

- Worker pay (profit split) is just an `expense` where `paid_to_party` is the
  worker-party → labour cost is a correct historical fact, no wage recomputation.

### expense_item
| Column | Type | Null | Notes |
|---|---|---|---|
| expense_item_id | int PK | no | |
| expense_id | int FK→expense | no | |
| product_id | int FK→product | yes | what was bought (null for non-product lines) |
| customer_order_id | int FK→customer_order | yes | attribute a cost to an order |
| expense_category_id | int FK→expense_category | no | controlled vocabulary |
| description | varchar | yes | |
| quantity | int | no | > 0 |
| unit_cost | numeric(10,2) | no | **historical snapshot** |
| comment | text | yes | |

### inventory_update  *(header)* + inventory_update_item  *(lines)*
inventory_update:
| Column | Type | Null | Notes |
|---|---|---|---|
| inventory_update_id | int PK | no | |
| type | varchar | no | purchase / order_usage / damage / correction |
| date | date | no | |
| comment | text | yes | |

inventory_update_item:
| Column | Type | Null | Notes |
|---|---|---|---|
| inventory_update_item_id | int PK | no | |
| inventory_update_id | int FK→inventory_update | no | |
| required_item_id | int FK→required_item | no | **stock is tracked here, not per product** |
| quantity_change | int | no | signed (delta model — see open notes) |
| expense_item_id | int FK→expense_item | yes | provenance: which purchase caused +N |
| customer_order_id | int FK→customer_order | yes | provenance: which order consumed −N |
| comment | text | yes | |

Current stock per required_item:
```sql
SELECT required_item_id, SUM(quantity_change)
FROM inventory_update_item
GROUP BY required_item_id;
```
A purchase of a `product` increases the stock of its `required_item`
(`product.required_item_id`).

### work
| Column | Type | Null | Notes |
|---|---|---|---|
| work_id | int PK | no | |
| party_id | int FK→party | no | a party with is_worker = true |
| start_at | timestamp | yes | date + time |
| end_at | timestamp | yes | date + time |
| break_minutes | int | yes | |
| tasks_accomplished | text | yes | free text for now (see open notes) |
| comment | text | yes | |

- No wage/cost here: labour cost lives in `expense`.
- **`work` ↔ `customer_order` is many-to-many** via `work_order`: a shift usually
  covers all the compositions/orders built that day. No link = general internal
  work; a single-order day is just the 1:1 case. (Replaces the old single
  `work.customer_order_id`.)

### work_order  *(M:N link: sessions ↔ orders)*
| Column | Type | Null | Notes |
|---|---|---|---|
| work_id | int FK→work | no | part of composite PK |
| customer_order_id | int FK→customer_order | no | part of composite PK |

---

## Relationship summary
```
party ─┐ (is_customer)  → customer_order.customer_party_id (nullable)
       ├ (is_supplier)  → expense.paid_by / paid_to
       └ (is_worker)    → work.party_id
location 1─* customer_order 1─* order_item *─1 composition
order_item 1─* order_item_color *─1 color
composition 1─* requirements *─1 required_item
required_item 1─* product *─0..1 color
required_item 1─* inventory_update_item *─1 inventory_update
expense 1─* expense_item *─0..1 product
expense_item *─0..1 customer_order ; *─1 expense_category
inventory_update_item *─0..1 expense_item ; *─0..1 customer_order
work *─* customer_order  (via work_order)
```

## Master vs historical (what may change vs frozen facts)
- **May change (master):** party contacts, composition.standard_price,
  required_item.minimum_safe_quantity, product links, expense_category list.
- **Frozen (historical):** order_item.unit_price, order_item.discount,
  order_item_color.color_surcharge, expense_item.unit_cost, expense totals,
  work timestamps, inventory movements.
- Labour cost is *not* derived from a current wage; it is whatever `expense`
  rows recorded (profit split) — already a frozen fact.

---

## 🟪 Finance & reporting tables *(added after the v2 baseline)*
These arrived after the original v2 spec above; they are live in the schema (see
migrations and [decisions.md](decisions.md) §14–19).


### monthly_report  *(frozen monthly PDF snapshot)*
| column | type | notes |
|---|---|---|
| monthly_report_id | int PK | |
| year, month | int | unique `(year, month)`; month 1..12 (CHECK) |
| status | str | `final` (closed month) \| `provisional` (current) (CHECK) |
| generated_at | datetime | last generation |
| revenue_total / expense_total / transfer_total / profit_total | numeric(10,2) | stored totals for the list |
| order_count / expense_count / transfer_count | int | |
| template_version | int | regenerate a `final` when the renderer version moves on |
| file_path | str | PDF path under `data/reports/`, relative to project root |
- Materialized lazily (no scheduler): closed months freeze when the reports list
  is opened. PDF built by `services/monthly_report` (reportlab).

### New columns on existing tables
- **location.active** (bool, default true) — retire a venue from new orders while
  keeping its history (used to merge Veranda → "Tenso/Veranda").
- **user_account.can_edit** (bool) — read-only accounts: viewers can read but not
  mutate (enforced server-side; UI hides edit controls).
- **product.package_quantity** (int, default 1) — pieces per purchased pack; stock
  refill multiplies expense quantity by this.
- **order_item_color.color_surcharge** (numeric(10,2), default 0) — see v2 spec.
- **expense_item.variant** (str) — digit for number-balloon purchases (refill split).
- **order_item_number** — per-digit foil numbers on a sold line (digit, colour, size).

---

## Open / parked decisions (to revisit)
1. **Inventory: delta vs snapshot.** Current spec uses a signed-delta ledger. The
   alternative (periodic absolute snapshots) is parked; do not mix both meanings
   in one `type` without a clear derivation rule.
2. **Work tasks: free text vs `task_type`.** Spec uses free text
   `tasks_accomplished` for now. Keeping a `task_type` (FK, or M:N if a session
   covers several tasks) would enable "hours per task type" analytics. Parked.
3. **Combos (P01–P04) cannot be decomposed into sub-compositions.** The BOM links
   composition→required_item, not composition→composition. If combos must expand
   into their member compositions automatically, a composition→composition link
   is needed. Parked.
4. **Controlled vocabularies to finalize:** `customer_order.state`, `event_type`,
   `celebrant_gender`, `required_item.type`, `required_item.unit`,
   `inventory_update.type` — decide the exact allowed values.
5. **Optional stored `work.duration`** as a faster alternative to computing from
   start/end − break (risks inconsistency; parked).

## Migration impact (when we implement)
- New/renamed tables: `party`, `required_item`, `requirements`,
  `inventory_update(_item)`, `customer_order`; removed: `customer`, `supplier`,
  `worker`, `task_type` (parked), `inventory_movement`.
- `master_data.toml` gets new sections: `party` (with role flags) instead of
  `supplier`/`customer`/`worker`; `required_item`; `requirements`; updated
  `product`. Existing colours/locations/compositions carry over.
- Because v1 has no real transactional data yet, migration can be a clean rebuild
  (drop + recreate + reload from the TOML) rather than a data-preserving upgrade.
```