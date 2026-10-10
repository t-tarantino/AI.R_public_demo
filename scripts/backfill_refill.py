"""Backfill stock refill for expenses that already bought products.

Historical expenses were imported without generating their `purchase` inventory
movements, so product purchases never raised stock. This replays the same
engine used on expense creation (build_refill) for every expense whose product
lines have no refill yet.

IDEMPOTENT: an expense already refilled is skipped, so it is safe to re-run.

    python -m scripts.backfill_refill
"""
from __future__ import annotations

from app.db.models import Expense
from app.db.session import SessionLocal
from app.services.refill import build_refill, expense_already_refilled


def run() -> None:
    db = SessionLocal()
    try:
        expenses = db.query(Expense).order_by(Expense.date, Expense.expense_id).all()
        created = skipped = no_product = total_lines = 0
        for expense in expenses:
            if expense_already_refilled(db, expense.expense_id):
                skipped += 1
                continue
            update = build_refill(db, expense)
            if update is None:
                no_product += 1
                continue
            db.add(update)
            created += 1
            total_lines += len(update.items)

        db.commit()
        print(f"Expenses scanned        : {len(expenses)}")
        print(f"Refill generated        : {created} updates ({total_lines} lines)")
        print(f"Already refilled        : {skipped} (skipped)")
        print(f"No product / nothing in : {no_product}")
    finally:
        db.close()


if __name__ == "__main__":
    run()