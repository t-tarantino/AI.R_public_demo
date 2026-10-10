> ⚠️ **Superseded.** This describes the original **v1** schema. The database now
> implements **v2** — see [data_model_v2.md](data_model_v2.md). This file is kept
> for history only.

# AI.R Internal System — Data Model (v1, historical)

This document describes every table in the initial schema: purpose, primary key,
foreign keys, nullable fields, constraints, cardinalities, and — importantly —
which values are **current/default master data** (may change) versus
**historical snapshots** (must never be recomputed).

Conventions:
- Surrogate integer primary keys named `<entity>_id` (see [decisions.md](decisions.md)).
- Money: `NUMERIC(10,2)`, never float.
- Percentages: `NUMERIC(5,2)`, `0..100` representation.
- `snake_case` table and column names.
- Nullable means the value is genuinely optional / "not applicable"; NULL is used
  rather than a sentinel value.

Legend: 🟦 master/current-value table · 🟧 historical/transactional table.

---

## 🟦 Master / informative tables

### customer
Reusable customer identity and current/default contact info.

| Column | Type | Null | Notes |
|---|---|---|---|
| customer_id | int PK | no | immutable identity |
| name | varchar(200) | no | |
| phone | varchar(50) | yes | |
| email | varchar(200) | yes | |
| default_discount | numeric(5,2) | yes | **current default only**, not proof of any past order discount |
| comment | text | yes | |

Constraints: `default_discount` between 0 and 100 when present.
Cardinality: one customer → many orders.

### location
Recurring/reusable venues.

| Column | Type | Null | Notes |
|---|---|---|---|
| location_id | int PK | no | |
| name | varchar(200) | no | |
| address | varchar(400) | yes | |
| comment | text | yes | |

Cardinality: one location → many orders.
Flagged: one-off private addresses are **not** modelled yet; when needed, add an
optional free-text address to `orders` rather than creating throwaway locations.

### composition
A sellable balloon composition/product-of-service.

| Column | Type | Null | Notes |
|---|---|---|---|
| composition_id | int PK | no | immutable identity |
| code | varchar(50) UNIQUE | no | human-readable, **may change** |
| name | varchar(200) | no | may change |
| standard_price | numeric(10,2) | no | **current/default price**; historical price is `order_item.unit_price` |
| estimated_working_time | int (minutes) | yes | provisional |
| estimated_large_balloons | int | yes | provisional |
| estimated_small_balloons | int | yes | provisional |
| active | bool | no | default true |
| comment | text | yes | |

Constraints: `standard_price >= 0`; `code` unique.
Cardinality: one composition → many order_items.
Flagged: balloon-estimate columns are provisional and may later be replaced by a
normalized composition-requirements table.

### color
Conceptual color (not a purchasable SKU).

| Column | Type | Null | Notes |
|---|---|---|---|
| color_id | int PK | no | |
| code | varchar(50) UNIQUE | no | |
| name | varchar(100) | no | |
| active | bool | no | default true |
| comment | text | yes | |

Constraints: `code` unique.
Cardinality: one color → many order_item_colors; one color → many products.
Note: brand/size/cost/supplier deliberately **do not** live here.

### supplier
| Column | Type | Null | Notes |
|---|---|---|---|
| supplier_id | int PK | no | |
| name | varchar(200) | no | |
| website | varchar(300) | yes | |
| category | varchar(100) | yes | |
| comment | text | yes | |

Cardinality: one supplier → many expenses.
Flagged: supplier-specific product URLs/prices will later need a
`supplier_product` link table; not built yet.

### expense_category
| Column | Type | Null | Notes |
|---|---|---|---|
| expense_category_id | int PK | no | |
| name | varchar(100) UNIQUE | no | e.g. materials, transport, fuel, software |

Cardinality: one category → many expenses.

### product
A specific physical purchasable product/SKU.

| Column | Type | Null | Notes |
|---|---|---|---|
| product_id | int PK | no | |
| product_code | varchar(50) | yes | |
| name | varchar(200) | no | |
| category | varchar(100) | yes | |
| brand | varchar(100) | yes | |
| color_id | int FK→color | yes | not all products have a conceptual color |
| size | varchar(50) | yes | |
| package_quantity | int | yes | |
| active | bool | no | default true |
| comment | text | yes | |

**No `cost` column** (historical cost = `expense_item.unit_cost`).
**No `quantity` column** (stock is derived from `inventory_movement`).
Cardinality: one product → many expense_items; one product → many inventory_movements.

### worker
| Column | Type | Null | Notes |
|---|---|---|---|
| worker_id | int PK | no | |
| name | varchar(200) | no | |
| code | varchar(50) UNIQUE | yes | unique when present |
| contact | varchar(200) | yes | |
| active | bool | no | default true |
| comment | text | yes | |

Cardinality: one worker → many work entries.
Note: no live hourly rate column — historical labour cost is snapshotted on `work`.

### task_type
| Column | Type | Null | Notes |
|---|---|---|---|
| task_type_id | int PK | no | |
| name | varchar(100) UNIQUE | no | e.g. preparation, installation, transport |
| comment | text | yes | |

Cardinality: one task_type → many work entries.

---

## 🟧 Historical / transactional tables

### orders
One row = one customer order/event. (Table is named `orders`, not `order`,
because `order` is a reserved SQL keyword — see [decisions.md](decisions.md).)

| Column | Type | Null | Notes |
|---|---|---|---|
| order_id | int PK | no | |
| customer_id | int FK→customer | no | FK, **not** PK |
| location_id | int FK→location | no | |
| date | date | no | |
| total_price | numeric(10,2) | no | actual customer-facing total (not `total_cost`) |
| comment | text | yes | |

Constraints: `total_price >= 0`.
Cardinality: one order → many order_items (cascade delete).

### order_item
One row = one composition sold inside an order.

| Column | Type | Null | Notes |
|---|---|---|---|
| order_item_id | int PK | no | |
| order_id | int FK→orders | no | |
| composition_id | int FK→composition | no | |
| quantity | int | no | |
| unit_price | numeric(10,2) | no | **historical selling price snapshot** |
| discount | numeric(5,2) | yes | percentage 0..100 |
| comment | text | yes | |

Constraints: `quantity > 0`; `unit_price >= 0`; `discount` in 0..100 when present.
Cardinality: one order_item → many order_item_colors (cascade delete).

### order_item_color
One row = one color used in one specific sold composition.

| Column | Type | Null | Notes |
|---|---|---|---|
| order_item_color_id | int PK | no | |
| order_item_id | int FK→order_item | no | references the **item**, not the composition |
| color_id | int FK→color | no | |
| color_percentage | numeric(5,2) | yes | 0..100 |
| comment | text | yes | |

Constraints: UNIQUE `(order_item_id, color_id)`; `color_percentage` in 0..100 when present.
Cardinality: one order_item → many order_item_colors; one color → many rows.
Flagged: the "percentages should sum to 100" rule is **not** enforced in the DB
(it is only meaningful when all percentages are provided); enforce in the
application layer when the entry UI exists.

### expense
One row = one expense/purchase event.

| Column | Type | Null | Notes |
|---|---|---|---|
| expense_id | int PK | no | |
| supplier_id | int FK→supplier | yes | some purchases have no recorded supplier |
| order_id | int FK→orders | yes | most expenses are general, not order-linked |
| expense_category_id | int FK→expense_category | no | |
| date | date | no | |
| total_cost | numeric(10,2) | no | actual total paid |
| payment_method | varchar(50) | yes | |
| comment | text | yes | |

Constraints: `total_cost >= 0`.
Cardinality: one expense → zero-or-many expense_items (cascade delete).

### expense_item
One row = one product line within a purchase.

| Column | Type | Null | Notes |
|---|---|---|---|
| expense_item_id | int PK | no | |
| expense_id | int FK→expense | no | |
| product_id | int FK→product | no | |
| quantity | int | no | |
| unit_cost | numeric(10,2) | no | **historical purchase cost snapshot** |
| comment | text | yes | |

Constraints: `quantity > 0`; `unit_cost >= 0`.
Cardinality: one product → many historical expense_items.

### work
One row = one historical work session/activity.

| Column | Type | Null | Notes |
|---|---|---|---|
| work_id | int PK | no | |
| worker_id | int FK→worker | no | |
| order_id | int FK→orders | yes | some work is general internal work |
| task_type_id | int FK→task_type | yes | |
| date | date | no | |
| start_time | time | yes | |
| end_time | time | yes | |
| duration_minutes | int | yes | duration stored in whole minutes |
| hourly_rate | numeric(10,2) | yes | **historical snapshot** rate for this entry |
| comment | text | yes | |

Constraints: `duration_minutes >= 0` when present; `hourly_rate >= 0` when present.
Cardinality: one worker/order/task_type → many work entries.
Flagged: when both start/end and duration are supplied, consistency is validated
in the application layer (see [decisions.md](decisions.md)); the DB stores minutes.

### inventory_movement
One row = one stock change. Current stock is **derived**, never stored.

| Column | Type | Null | Notes |
|---|---|---|---|
| inventory_movement_id | int PK | no | |
| product_id | int FK→product | no | |
| date | date | no | |
| quantity_change | int | no | signed: +in / −out |
| movement_type | varchar(50) | no | purchase, order_usage, damaged, stock_correction |
| expense_item_id | int FK→expense_item | yes | links a purchase movement to its purchase line |
| order_id | int FK→orders | yes | links a usage movement to its order |
| comment | text | yes | |

Derived current stock:
```sql
SELECT product_id, SUM(quantity_change) AS stock
FROM inventory_movement
GROUP BY product_id;
```

---

## Relationship summary

```
customer 1─* orders *─1 location
orders 1─* order_item *─1 composition
order_item 1─* order_item_color *─1 color
expense_category 1─* expense *─0..1 supplier
expense *─0..1 orders
expense 1─* expense_item *─1 product
product *─0..1 color
worker 1─* work *─0..1 orders
task_type 1─* work
product 1─* inventory_movement *─0..1 expense_item
inventory_movement *─0..1 orders
```
