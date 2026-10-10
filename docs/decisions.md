# Architecture Decision Record — AI.R Internal System

Short records of the decisions that shape the schema and stack. Each entry notes
the decision, the reasoning, and any trade-off.

---

## 1. PostgreSQL is the target database; SQLite is a temporary bootstrap
**Decision.** The intended production database is PostgreSQL. Because neither
PostgreSQL nor Docker is installed on the dev machine, the project starts on a
file-based SQLite database (`air.db`) so work can begin immediately.

**How compatibility is preserved.**
- The database is configured in exactly one place: `DATABASE_URL` in `.env`.
  Switching to Postgres is a one-line change (`postgresql+psycopg://...`).
- `psycopg` (Postgres driver) is already a dependency, so no reinstall is needed.
- Types chosen work on both engines: `NUMERIC(10,2)`, `DATE`, `TIME`, `TEXT`,
  `VARCHAR(n)`, integer PKs, CHECK/UNIQUE/FK constraints.
- SQLite normally ignores foreign keys; we enable `PRAGMA foreign_keys=ON` on
  every connection so referential integrity behaves like Postgres during
  bootstrap.
- Alembic uses `render_as_batch=True` so schema-altering migrations also run on
  SQLite.

**Trade-off.** SQLite is more permissive than Postgres about types and
concurrency, so a migration that runs on SQLite is not a 100% guarantee it runs
on Postgres. Before going to production, the migrations must be run once against
a real Postgres instance. This is acceptable for a bootstrap.

---

## 2. Surrogate integer primary keys, one naming convention
**Decision.** Every table has an auto-generated integer PK named `<entity>_id`
(`customer_id`, `order_id`, ...). Foreign keys reuse the referenced column name.

**Reasoning.** For a small private system, integer PKs are simpler and smaller
than UUIDs and read well in URLs/logs. A single naming convention avoids the
`id_color` vs `color_id` confusion called out in the brief.

**Trade-off.** Integer IDs are guessable and reveal row counts; irrelevant for a
private internal tool. UUIDs can be adopted later per-table if an entity ever
needs to be created offline/merged across databases.

---

## 3. Master (current) values vs historical snapshots are separated
**Decision.** Current/default values live on master tables and may change:
`composition.standard_price`, `customer.default_discount`, and the (future)
worker rate. The value that actually applied to a past transaction is copied
into the transactional row at the time it happens:
`order_item.unit_price`, `order_item.discount`, `expense_item.unit_cost`,
`work.hourly_rate`.

**Reasoning.** Historical facts must stay correct even after prices/rates change.
Reconstructing an old price from today's master value would silently corrupt
history and any profit/analytics built on it.

**Trade-off.** The "same" price is duplicated (once as the current default, once
as each historical snapshot). This denormalization is intentional and standard
for financial/transactional data — it is not a normalization mistake.

---

## 4. `order_item_color` references `order_item`, not `composition`
**Decision.** Colors used are attached to the specific sold line
(`order_item_id`), not to the composition.

**Reasoning.** The same composition can be sold in completely different colors in
different orders. Attaching colors to the composition would make color a fixed
property of the product, which is false. A UNIQUE `(order_item_id, color_id)`
prevents accidentally listing the same color twice on one line.

**Trade-off.** Colors are recorded per order rather than defaulted from the
composition, so data entry repeats color choices. A future "default colors for a
composition" feature can pre-fill the UI without changing this table.

---

## 5. Stock is derived from `inventory_movement`, never stored on `product`
**Decision.** There is no `product.quantity`. Current stock is
`SUM(inventory_movement.quantity_change) GROUP BY product_id`.

**Reasoning.** A single stored "current quantity" is a second source of truth
that drifts out of sync with the events that changed it. A signed movement ledger
is auditable (you can see *why* stock changed) and always reconstructable.

**Trade-off.** Reading current stock requires an aggregate query rather than a
column read. If this ever becomes a performance problem, a cached
`current_quantity` may be added **only** as an explicitly-documented cache kept
consistent by the movement writes — never as the authoritative value.

---

## 6. Money and percentages use fixed-precision numeric types
**Decision.** Money is `NUMERIC(10,2)`. Percentages are `NUMERIC(5,2)` in a
`0..100` representation, range-checked by CHECK constraints.

**Reasoning.** Floating point cannot represent decimal currency exactly and
accumulates rounding errors. `0..100` (rather than `0..1`) matches how discounts
and color mixes are spoken about in the business.

**Trade-off.** `NUMERIC(10,2)` caps a single amount below 100,000,000.00, which
is far beyond this business's needs and can be widened by a migration if ever
required.

---

## 7. Work duration is stored in whole minutes
**Decision.** `work` keeps optional `start_time`/`end_time` **and** an integer
`duration_minutes`. The column is named `duration_minutes` (not just `duration`)
to make the unit unambiguous.

**Reasoning.** Minutes are precise enough for labour tracking, easy to sum for
"total hours", and portable across SQLite and Postgres (neither needs a special
INTERVAL type). Some entries will only have a duration (no clock times), so
storing it explicitly is necessary.

**Trade-off.** When both clock times and a duration are supplied they can
disagree. Rather than a rigid DB rule, consistency (derive/validate duration from
start/end) is enforced in the application layer when the data-entry UI is built.
This is flagged so it is not forgotten.

---

## 8. Table named `orders` because `order` is reserved
**Decision.** The order table is `orders`; the model class is `Order` and the key
is `order_id`.

**Reasoning.** `ORDER` is a reserved keyword in PostgreSQL; an unquoted `order`
table causes errors and forces quoting everywhere. `orders` is the conventional
workaround. This is a naming-only change; the domain model is unchanged.

**Trade-off.** Slight inconsistency with the otherwise-singular table names
(`customer`, `composition`). Correctness/portability wins over cosmetic
uniformity.

---

## 9. Alembic migrations, URL sourced from app settings
**Decision.** Migrations are managed by Alembic. `migrations/env.py` reads
`DATABASE_URL` from `app.config`, and `target_metadata` is the ORM `Base`
metadata, so autogenerate and the app can never disagree about the schema or the
target database.

**Trade-off.** Autogenerate output should still be reviewed before applying —
it is a starting point, not a guarantee — but this keeps a single source of truth.

---

## 10. Off-catalog colours and their surcharge
**Decision.** A colour carries `color.in_catalog` (bool). Off-catalog colours
(e.g. Bordeaux, Blu scuro) are stored as normal, reusable rows with
`in_catalog = false`. The surcharge charged when such a colour is chosen is a
historical monetary amount on `order_item_color.color_surcharge`; the base list
price stays in `order_item.unit_price`.

**Reasoning.** The catalog status is a stable, reusable property of the colour,
not of a single order. The surcharge, instead, is a fact of the specific order
line and is *caused by* the chosen colour — so it belongs on `order_item_color`
(the row that links that colour to that line), not on the composition (whose
price is order-independent) nor as a separate synthetic order_item. This keeps
`unit_price` honest and makes surcharge revenue trivially queryable
(`SUM(color_surcharge)`, joinable to `color WHERE in_catalog = 0`).

**Trade-off.** Only the amount is stored, not a "+N%" rule; the percentage is a
business convention frozen per line as a historical fact. Introduced by
migration `c4e1a9b7d2f3`.

---

## 11. Work relates to orders many-to-many (`work_order`)
**Decision.** A `work` session links to orders through the association table
`work_order` (M:N), replacing the old single `work.customer_order_id`.

**Reasoning.** In practice a shift covers *all* the compositions built that day,
across several locations/orders — not one order. A single FK could not express
this; a day with one order is simply the 1:1 special case. Work still has one row
per worker (their start/end/break/tasks differ); the M:N is a separate axis
(session ↔ orders). The loader links a session to every order sharing its date.

**Trade-off.** The web API for work now takes/returns `order_ids: list[int]`
instead of a scalar. Sessions with no link are valid (general internal work).
Introduced by migration `d7f2a1c9e4b8`.

---

## 12. Master sync is a non-destructive UPSERT; SQLite path is absolute
**Decision.** `scripts/import_data` no longer wipes and reloads. It UPSERTs
master rows by natural key (color.code, composition.code, location.name,
party.code_nickname/name, expense_category.name, required_item.name, product) so
**IDs stay stable** and transactional foreign keys survive; it never touches
transactional tables. Pure-master child tables with no transactional FK
(`requirements`, `stock_threshold`) are rebuilt. Rows removed from the TOML are
reported, not deleted (retire them with `active = false`). Separately, a relative
`sqlite:///./air.db` URL is anchored to the project root in `db/session.py`.

**Reasoning.** Once real orders/work/expenses exist, wipe-and-reload would delete
them or invalidate FKs by recreating masters with new ids. Updating data is the
core capability of the system, so it must be safe and repeatable. The absolute
sqlite path removes the "app opened a different, empty air.db" trap that depends
on the launch directory.

**Trade-off.** Deletions are not propagated automatically (safe default). Natural
keys must stay stable (renaming a code = a new row); acceptable for master data.

---

## 13. The business and its partner are parties; `party.is_business`
**Decision.** Added `party.is_business` and included it in the `at_least_one_role`
check (migration `e5a3f1b9c7d2`). Two entities are modelled:
- **AI.R** (`is_business=true`): our own company (the four partners as one
  entity, distinct from them as individual workers).
- **Riverside Hall** (`is_customer=true`): the external partner. It is the customer of
  our orders (AI.R provides the balloon service to Riverside Hall) and it pays for
  the material purchases that AI.R then uses.

So material expenses are `paid_by = Riverside Hall`, `paid_to = supplier`; the "used by
AI.R" attribution lives in the expense `comment` (no dedicated column yet).
Orders carry `customer_party_id = Riverside Hall`.

**Reasoning.** The expense model requires both a payer and a payee, and the
business/partner had no representation. Distinguishing AI.R (entity) from the
partner-workers keeps books clean and reflects the real inverse flows (Riverside Hall
buys services from AI.R; Riverside Hall funds the supplies).

**Trade-off.** The supply flow (Riverside Hall pays, AI.R uses) isn't modelled as a
formal inter-party attribution; it's a comment note, to be formalised later if
needed. Imported balloon SKUs use a synthetic `product_code`
(`<color>-<SELLER>-<G|P>`) since suppliers give no stable SKU.

---

## 14. Order total is derived from its lines (coherence invariant)
**Decision.** `customer_order.total_price` is computed by the server as the sum of
line totals — `Σ (unit_price × qty × (1 − discount) + Σ colour_surcharge)` — on
create and on item replace (`app/api/orders_api.py`). A provided total is overridden.

**Reasoning.** Two views read revenue differently: the **customer's debt**
(`money_balances`) uses `total_price`, while **profit / Analytics** use the
line-level `derive` revenue. If they diverge (e.g. a bad import missing a surcharge
or a line), balances and reports silently disagree — a real bug we hit. Deriving
the total makes *total = Σ lines* true by construction, so both agree.

**Trade-off.** No free-hand "negotiated" total independent of the lines; a discount
or surcharge must be expressed on a line. New order lines default to a 10% discount
and off-catalogue colours auto-fill a 10% surcharge, so the derived total matches
how the business actually prices.

## 16. Monthly reports: lazy materialization + template version
**Decision.** `monthly_report` stores one frozen PDF snapshot per month (totals +
file path). Because there is **no scheduler**, `services/monthly_report.materialize`
freezes every *closed* month when the reports list is opened; the current month is
`provisional` and regenerable. A `template_version` column forces regeneration of
`final` reports when the PDF layout changes.

**Reasoning.** The backend is not always-on, so "save automatically at month end"
is implemented as lazy-on-access. `template_version` avoids stale layouts on old
finals after a template change.

**Trade-off.** A report only freezes the first time someone opens the list in the
new month (fine in practice). PDFs live under `data/reports/` on the server disk.

## 17. Orders auto-complete lazily (`order_lifecycle`)
**Decision.** Listing orders (and building reports) moves any **confirmed** order
whose event date is strictly in the past to **completed**, generating consumption
once — mirroring manual completion. Drafts and cancelled orders are untouched.

**Reasoning.** No scheduler; the event has happened, so revenue/stock should reflect
it without manual clicks. The order list is the natural, most-visited trigger.

**Trade-off.** State changes on a GET (a deliberate, idempotent side effect); the
current day is left confirmed until it is strictly past.

## 18. Read-only accounts (`user_account.can_edit`)
**Decision.** Accounts carry `can_edit`; the server rejects mutations from viewers
and the frontend (`lib/user`, `useCanEdit`) hides create/edit/delete controls.
`is_admin` remains for account administration.

**Reasoning.** Helpers should see the data without being able to change it, without
inventing per-endpoint permissions.

## 19. Soft-retire vs delete; guarded delete for expense categories
**Decision.** Referenced master records are **deactivated**, not deleted, via an
`active` flag (colours, compositions, products, and now **locations** —
`location.active`, used to retire "Veranda" after merging it into "Tenso/Veranda").
Expense categories are the exception: they support **hard delete**, but a guard
(`DELETE /api/expense_category/{id}`) refuses if any expense line uses the category
and reports how many and the most recent example.

**Reasoning.** History must never dangle. `active` hides a record from new entries
while keeping past references valid; the guarded delete gives real removal only
when it is safe, with a helpful message otherwise.
