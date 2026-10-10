"""Automatic order-status transitions.

The backend isn't a long-running process, so there is no cron to close orders
once their event day has passed. Instead we reconcile lazily: whenever orders
are listed (or a report is built), any order still `confirmed` whose event date
is strictly in the past is treated as done and moved to `completed` — mirroring
the manual completion path, including one-off theoretical consumption.

Draft orders are never auto-completed (they are not commitments); cancelled
orders are left untouched.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.db.models import CustomerOrder, User
from app.services.audit import log_action
from app.services.consumption import build_consumption, order_already_consumed


def auto_complete_due(db: Session, today: date | None = None,
                      user: User | None = None) -> int:
    """Complete past confirmed orders. Returns how many were completed.

    If `user` is given, each transition is recorded in the activity log
    (attributed to whoever triggered the reconciliation).
    """
    today = today or date.today()
    due = (db.query(CustomerOrder)
           .filter(CustomerOrder.state == "confirmed", CustomerOrder.date < today)
           .all())
    completed = 0
    for order in due:
        order.state = "completed"
        consumption_lines = 0
        if not order_already_consumed(db, order.customer_order_id):
            update = build_consumption(db, order)
            if update is not None:
                db.add(update)
                consumption_lines = len(update.items)
        if user is not None:
            log_action(db, user, "update", "customer_order", order.customer_order_id,
                       {"state": {"da": "confirmed", "a": "completed"}, "auto": True})
            if consumption_lines:
                log_action(db, user, "create", "inventory_update", None,
                           {"order_usage": f"order #{order.customer_order_id}",
                            "lines": consumption_lines, "auto": True})
        completed += 1
    if completed:
        db.commit()
    return completed
