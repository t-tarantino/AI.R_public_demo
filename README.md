# AI.R public demo

> **Portfolio / demo project.** This is a sanitized, public showcase of a real
> management app I built and run for a small event-decoration business. The real
> name, customers, finances and production data are **not** included: everything
> here — company name, people, venue, prices, master data — is **fictional demo
> data**. Run it locally with the bundled example seed (see *Setup*) to explore
> the full feature set. The production instance and its data remain private.

Public demo of an internal management system (**AI.R**), a small
event-decoration business specialized in balloon installations. It includes
a **mobile-first web app** to view and edit the operational dataset, with
per-user login and a who-did-what audit log.

- **Backend:** Python 3.12 · FastAPI · SQLAlchemy 2.x · Alembic · Pydantic · pytest
- **Frontend:** React 19 · Vite · TypeScript · Tailwind CSS (in `frontend/`)
- **Database:** PostgreSQL is the intended production database. Development
  currently runs on a temporary local **SQLite** file; the schema and code stay
  PostgreSQL-compatible (switching is a one-line `DATABASE_URL` change). See
  [docs/decisions.md](docs/decisions.md).

## Documentation
- [docs/data_model_v2.md](docs/data_model_v2.md) — authoritative schema (every table,
  key, constraint; master-vs-historical distinction).
- [docs/decisions.md](docs/decisions.md) — architectural decisions and trade-offs (ADRs).
- [DEPLOY.md](DEPLOY.md) — Render + Supabase deployment.

---

## Prerequisites
- Python 3.12+
- Git

That's it for the SQLite bootstrap. PostgreSQL is only needed later (see below).

## Setup

From the `ai-r/` directory:

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # PowerShell
# .venv\Scripts\activate.bat        # cmd.exe
# source .venv/bin/activate         # macOS/Linux

# 2. Install the project + dev dependencies
pip install -e ".[dev]"

# 3. Create your local env file
copy .env.example .env              # PowerShell/cmd
# cp .env.example .env              # macOS/Linux

# 4. Create the database schema
alembic upgrade head

# 5. Load master data. Copy the bundled demo seed first (real master_data.toml
#    is git-ignored), then import it:
#    copy data\master_data.example.toml data\master_data.toml   (PowerShell/cmd)
#    cp data/master_data.example.toml data/master_data.toml      (macOS/Linux)
python -m scripts.import_data

# 6. Create web-app user accounts (al/bo/ca/da, initial password 'demo1234'; al=admin)
python -m scripts.create_users

# 7. (optional) Load a fake 4-month operational history (Sep-Dec 2026) so the
#    demo shows orders, expenses, transfers and work hours instead of empty screens.
python -m scripts.seed_demo

# 8. Frontend dependencies (Node.js 18+ required)
cd frontend
npm install
cd ..
```

Master data is maintained in [data/master_data.toml](data/master_data.toml) as the
single source of truth. Edit that file and re-run `python -m scripts.import_data`
to rebuild the master tables — user accounts and the audit log survive the reload.
The web app writes to the same database directly.

## Run the web app (two dev servers)

```powershell
# Terminal 1 — backend API
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

# Terminal 2 — frontend
cd frontend
npm run dev
```

Then open **http://localhost:5173** (or, from a phone on the same network,
`http://<pc-ip>:5173`) and log in. Initial accounts: `al` (admin), `bo`,
`ca`, `da` — password `demo1234`, to be changed from ⚙️ Impostazioni.

Backend-only URLs:
- http://127.0.0.1:8000/health — liveness
- http://127.0.0.1:8000/health/db — database connectivity
- http://127.0.0.1:8000/docs — interactive API docs (Swagger UI)

### Web app features
- **Operational entry** from the phone:
  - **🎈 Orders** — orders with nested items, colour mixes and foil numbers. The
    **total is derived from the lines** (10% default discount; off-catalogue
    colours auto-add a 10% surcharge). Completing an order generates theoretical
    stock consumption from the BOM; past confirmed orders **auto-complete** on view.
  - **💶 Expenses** — nested lines; product lines **auto-refill stock** (packs→pieces).
  - **⏱️ Time** — work sessions (start/end + break + tasks).
  - **🔄 Transfers** — cash movements between any two parties.
  - **🔄 Stock movements** — manual purchases/corrections (append-only).
- **💰 Money** — revenue/costs/profit, **balances** (who owes whom),
  unified money-flow list.
- **📊 Analytics** — flexible metric explorer (metrics × breakdown × filters).
- **🧾 Monthly reports** — frozen PDF per month (revenue/expenses/transfers with
  subtotals), materialized lazily.
- **Master-data CRUD**: price list/compositions (incl. **BOM editor**), colours,
  parties, locations, materials, **products** (browsed by material → colour),
  stock thresholds, expense categories (add/edit/**delete with in-use guard**).
  Referenced records are **deactivated** (`active`) rather than deleted.
- **📦 Stock** — derived from inventory movements (per material + colour + digit),
  red flag below the effective minimum threshold.
- **📝 Activity** — audit log of data changes (who/what/when), operations vs master.
- **Roles** — accounts have `is_admin` and **`can_edit`**; read-only accounts see
  everything but cannot mutate. **⚙️ Settings** — change your password.

## Run the tests

```powershell
pytest
```

Tests run against a throwaway in-memory SQLite database, so they never touch
your local `air.db`.

---

## Database migrations (Alembic)

The migration environment reads `DATABASE_URL` from `.env`, so migrations always
target the same database as the app.

```powershell
alembic upgrade head                              # apply all migrations
alembic downgrade -1                              # roll back one
alembic revision --autogenerate -m "describe it"  # after changing models
alembic current                                   # show applied revision
alembic history                                   # list migrations
```

> After editing SQLAlchemy models, generate a migration and **review it** before
> applying — autogenerate is a starting point, not a guarantee.

## Switching to PostgreSQL

1. Install PostgreSQL and create a database and user, e.g.:
   ```sql
   CREATE DATABASE ai-r_dev;
   CREATE USER ai-r_user WITH PASSWORD 'ai-r_password';
   GRANT ALL PRIVILEGES ON DATABASE ai-r_dev TO ai-r_user;
   ```
2. In `.env`, replace the SQLite line with:
   ```
   DATABASE_URL=postgresql+psycopg://ai-r_user:ai-r_password@localhost:5432/ai-r_dev
   ```
3. Recreate the schema on Postgres:
   ```powershell
   alembic upgrade head
   ```
No application code changes are required — `psycopg` is already installed.

---

## Project layout

```text
ai-r/
├── app/
│   ├── main.py            # FastAPI app + router wiring
│   ├── config.py          # settings (pydantic-settings), reads .env
│   ├── api/health.py      # /health and /health/db endpoints
│   ├── db/
│   │   ├── base.py        # DeclarativeBase + naming conventions
│   │   ├── session.py     # engine, SessionLocal, get_db dependency
│   │   └── models/        # ORM models (master_data, bom, orders, expenses, work, inventory, system)
│   ├── api/               # REST routers: auth, crud, orders_api, transactions,
│   │                      #   dashboard, metrics, reports, stock, bom, activity
│   ├── schemas/           # Pydantic request/response models (master, transactional)
│   └── services/          # derive (metrics engine), metrics, consumption, refill,
│                          #   order_lifecycle, monthly_report, audit, security
├── frontend/              # React web app (Vite + TS + Tailwind)
├── migrations/            # Alembic environment + versioned migrations
├── data/                  # master_data.example.toml (demo seed; real data git-ignored)
├── scripts/import_data.py # loads master_data.toml into the DB
├── scripts/create_users.py# seeds web-app accounts
├── scripts/seed_demo.py   # loads a fake operational history for the demo
├── tests/                 # pytest suite
├── docs/                  # data_model_v2.md, decisions.md
├── DEPLOY.md              # Render + Supabase deployment
├── alembic.ini
├── pyproject.toml
├── .env.example
└── README.md
```

> **Schema version:** the database now implements **v2**. See
> [docs/data_model_v2.md](docs/data_model_v2.md) for the authoritative model.
> [docs/data_model.md](docs/data_model.md) describes the older v1 and is kept for
> history only.

## Design principles (enforced in the schema)
- An order's `total_price` is **derived from its line subtotals** (total = Σ lines),
  so customer debt and profit always agree. See [decisions.md](docs/decisions.md) §14.
- Historical facts (`order_item.unit_price`, `expense_item.unit_cost`,
  `order_item_color.color_surcharge`) are **snapshots**, never recomputed.
- Labour cost is recorded as `expense` (profit split), not derived from a wage.
- Current/default master values (`composition.standard_price`) may change freely.
- Stock is **derived** from inventory movements, tracked at the `required_item`
  level (not per product).
- Money is `NUMERIC(10,2)`; percentages are `NUMERIC(5,2)` in `0..100`.
- Immutable integer surrogate keys; human-readable codes/names may change.
