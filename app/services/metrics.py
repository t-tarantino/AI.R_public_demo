"""Convenience summary + upcoming orders, built on the derive engine.

The compositional engine (app/services/derive.py) is the single source of truth
for revenue/costs/profit/orders/hours. This module just assembles the handful of
scalars the dashboard header shows.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import CustomerOrder, Expense, MoneyTransfer, Party
from app.services import derive


def _scalar(db: Session, metric: str, start: date, end: date) -> Decimal:
    value = derive.evaluate(db, metric, start, end)
    return value if value is not None else Decimal(0)


def summary(db: Session, start: date, end: date) -> dict:
    rev = _scalar(db, "revenue", start, end)
    cst = _scalar(db, "costs", start, end)
    count = int(_scalar(db, "orders", start, end))
    hours = _scalar(db, "hours", start, end)
    avg_order = (rev / count) if count else Decimal(0)
    cents = Decimal("0.01")
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "revenue": rev.quantize(cents),
        "costs": cst.quantize(cents),
        "profit": (rev - cst).quantize(cents),
        "order_count": count,
        "avg_order_value": avg_order.quantize(cents),
        "worker_hours": round(float(hours), 1),
    }


def upcoming_orders(db: Session, today: date, days: int = 30) -> list[CustomerOrder]:
    """Confirmed orders scheduled from today through `today + days`."""
    return db.query(CustomerOrder).filter(
        CustomerOrder.state == "confirmed",
        CustomerOrder.date >= today,
        CustomerOrder.date <= today + timedelta(days=days),
    ).order_by(CustomerOrder.date).all()


def money_balances(db: Session) -> list[dict]:
    """Net amount AI.R (the business) owes each other party, right now.

    Positive amount = the business owes that party. Negative = that party
    owes the business. Combines three independent, extensible fact sources
    (new movement types can be added the same way without touching the others):

    - `expense`: whoever actually paid (`paid_by`) for a business cost is owed
      back by the business, unless the business itself paid directly.
    - `customer_order`: a completed order's `customer_party_id` owes the
      business its `total_price` (revenue not yet necessarily collected).
    - `money_transfer`: a plain cash movement between any two parties. The payer
      is credited (+amount), the receiver debited (-amount); the business's own
      side is dropped. A transfer thus settles debts through the business as hub,
      whether or not the business is one of the two parties.
    """
    business = db.query(Party).filter(Party.is_business.is_(True)).first()
    business_id = business.party_id if business else None
    balances: dict[int, Decimal] = {}

    def add(party_id: int | None, amount: Decimal) -> None:
        if party_id is None or party_id == business_id:
            return
        balances[party_id] = balances.get(party_id, Decimal(0)) + amount

    # 1) Expenses: a non-business payer fronted a business cost -> owed back.
    expense_totals = db.query(
        Expense.paid_by_party_id, func.sum(Expense.total_cost)
    ).group_by(Expense.paid_by_party_id).all()
    for payer_id, total in expense_totals:
        add(payer_id, Decimal(total))

    # 2) Orders: a completed order's customer owes the business its price.
    order_totals = db.query(
        CustomerOrder.customer_party_id, func.sum(CustomerOrder.total_price)
    ).filter(
        CustomerOrder.state == "completed",
        CustomerOrder.customer_party_id.isnot(None),
    ).group_by(CustomerOrder.customer_party_id).all()
    for customer_id, total in order_totals:
        add(customer_id, -Decimal(total))

    # 3) Transfers: a payment from A to B settles debts through the business as
    #    hub — the payer ends up owed more (or owing less), the receiver owed
    #    less (or owing more). The `add` guard drops the business's own side, so
    #    this works whether or not the business is one of the two parties (e.g. a
    #    client paying the workers directly settles the client's order debt AND
    #    what the business owes those workers).
    for t in db.query(MoneyTransfer).all():
        amount = Decimal(t.amount)
        add(t.from_party_id, amount)             # paid out -> owed more / owes less
        add(t.to_party_id, -amount)              # received -> owed less / owes more

    parties = {p.party_id: p for p in db.query(Party)}
    cents = Decimal("0.01")
    rows = []
    for party_id, amount in balances.items():
        amount = amount.quantize(cents)
        if amount == 0:
            continue
        p = parties.get(party_id)
        rows.append({
            "party_id": party_id,
            "name": p.name if p else f"#{party_id}",
            "code_nickname": p.code_nickname if p else None,
            "amount": amount,
        })
    rows.sort(key=lambda r: -r["amount"])
    return rows
