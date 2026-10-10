"""Copy all business data from the local SQLite `air.db` into the target
(PostgreSQL) database given by DATABASE_URL.

Both databases must be at the same Alembic schema revision (identical tables).
The copy runs in a single transaction: if anything fails, nothing is written.

Usage (from the project root, venv active):

    # DATABASE_URL must point at the TARGET Postgres (e.g. Supabase):
    $env:DATABASE_URL="postgresql+psycopg://.../postgres"   # PowerShell
    python -m scripts.copy_sqlite_to_postgres                # copy ./air.db
    python -m scripts.copy_sqlite_to_postgres path/to/other.db

Notes:
- `user_account` and `audit_log` are SKIPPED on purpose: the online DB already
  has the admin account you created, and the audit log references it. Login
  accounts are managed separately via `scripts.create_users`.
- Reading/writing through the SAME typed SQLAlchemy tables converts values
  correctly across dialects (SQLite 0/1 -> real Postgres booleans, text -> Date,
  Numeric, etc.).
- Integer-PK sequences are reset so the app keeps numbering new rows correctly.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, insert, select, text

import app.db.models  # noqa: F401  (registers every table on Base.metadata)
from app.config import settings
from app.db.base import Base

# Tables not to copy (see module docstring).
SKIP = {"user_account", "audit_log"}


def main() -> None:
    source_path = sys.argv[1] if len(sys.argv) > 1 else "air.db"

    target_url = settings.database_url
    if target_url.startswith("sqlite"):
        raise SystemExit(
            "DATABASE_URL points at SQLite. Set it to the target Postgres URL first,\n"
            "e.g. $env:DATABASE_URL=\"postgresql+psycopg://.../postgres\""
        )

    source = create_engine(f"sqlite:///{source_path}", future=True)
    target = create_engine(target_url, future=True)

    # FK-safe order: parents before children.
    ordered = list(Base.metadata.sorted_tables)
    to_copy = [t for t in ordered if t.name not in SKIP]

    print(f"Sorgente : {source_path}")
    print(f"Destinazione: {target_url.split('@')[-1]}")  # host only, no password
    print(f"Copio {len(to_copy)} tabelle (salto: {', '.join(sorted(SKIP))})\n")

    with source.connect() as src, target.begin() as dst:
        total = 0
        for table in to_copy:
            rows = [dict(r) for r in src.execute(select(table)).mappings()]
            if rows:
                dst.execute(insert(table), rows)
                total += len(rows)
            print(f"  {table.name:35s} {len(rows):>6} righe")

        print("\nRiallineo i contatori degli ID (sequenze)...")
        for table in to_copy:
            pk_cols = list(table.primary_key.columns)
            if len(pk_cols) != 1:
                continue  # composite PK -> no serial sequence
            col = pk_cols[0].name
            seq = dst.execute(
                text("SELECT pg_get_serial_sequence(:t, :c)"),
                {"t": table.name, "c": col},
            ).scalar()
            if not seq:
                continue
            maxid = dst.execute(
                text(f'SELECT COALESCE(MAX("{col}"), 0) FROM "{table.name}"')
            ).scalar()
            if maxid and maxid > 0:
                dst.execute(text("SELECT setval(:s, :v, true)"), {"s": seq, "v": maxid})

    print(f"\nFatto: {total} righe copiate. Transazione confermata.")


if __name__ == "__main__":
    main()