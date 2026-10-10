#!/bin/sh
# Apply any pending database migrations, then start the API server.
# Runs on every deploy: migrations are idempotent (alembic tracks what ran).
set -e

echo "Running database migrations..."
alembic upgrade head

# Public demo convenience: on an EMPTY database, load the fake master data +
# demo accounts + a fake operational history, so the live demo is populated on
# first boot. Guarded so it never clobbers a database that already has data,
# and non-fatal so a seeding hiccup can't stop the server from starting.
# Set SEED_DEMO=false to disable entirely.
if [ "${SEED_DEMO:-true}" = "true" ]; then
  if python -c "import sys; from app.db.session import SessionLocal; from app.db.models import Party; db=SessionLocal(); n=db.query(Party).count(); db.close(); sys.exit(1 if n else 0)"; then
    echo "Empty database detected — seeding demo data..."
    cp -f data/master_data.example.toml data/master_data.toml 2>/dev/null || true
    ( python -m scripts.import_data \
      && python -m scripts.create_users \
      && python -m scripts.seed_demo ) || echo "Demo seeding skipped/failed (continuing)."
  else
    echo "Database already has data — skipping demo seed."
  fi
fi

echo "Starting uvicorn on port ${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"