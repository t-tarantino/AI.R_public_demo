"""Backfill theoretical stock consumption for orders already marked completed.

Historical orders were bulk-imported straight into the 'completed' state, so
they never passed through the API transition that generates their
`order_usage` inventory movements. As a result the derived stock ignores
everything those orders consumed.

This script replays the SAME engine used on completion (build_consumption) for
every completed order that has no consumption yet. It is IDEMPOTENT: an order
that already has an order_usage movement is skipped, so it is safe to re-run.

    python -m scripts.backfill_consumption
"""
from __future__ import annotations

from app.db.models import CustomerOrder
from app.db.session import SessionLocal
from app.services.consumption import build_consumption, order_already_consumed


def run() -> None:
    db = SessionLocal()
    try:
        completed = (db.query(CustomerOrder)
                     .filter_by(state="completed")
                     .order_by(CustomerOrder.date, CustomerOrder.customer_order_id)
                     .all())
        created = skipped = no_bom = total_lines = 0
        for order in completed:
            if order_already_consumed(db, order.customer_order_id):
                skipped += 1
                continue
            update = build_consumption(db, order)
            if update is None:
                no_bom += 1
                continue
            db.add(update)
            created += 1
            total_lines += len(update.items)

        db.commit()
        print(f"Completed orders scanned : {len(completed)}")
        print(f"Consumption generated     : {created} updates ({total_lines} lines)")
        print(f"Already had consumption   : {skipped} (skipped)")
        print(f"No BOM / nothing to use   : {no_bom}")
    finally:
        db.close()


if __name__ == "__main__":
    run()