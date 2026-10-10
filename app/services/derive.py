"""Compositional derived-metrics engine (per docs/AI.R_Derived_Information_Model.md).

Design: a small set of GENERATORS (fact streams) + generic OPERATORS
(filter/group-by/aggregate/ratio/difference/compare). One evaluate() drives
everything, so the UI parameterises period + group_by + scope + compare instead
of the backend hard-coding one metric per view.

Everything is computed from primitive rows — nothing is stored. Data volumes are
small, so aggregation is done in Python (portable, no SQL-dialect date tricks)
and stays fully traceable.

Semantics (agreed):
- Revenue: sum of `customer_order.total_price` for **completed** orders, by event date.
- Costs: sum of `expense.total_cost`, by expense date.
- Profit: revenue - costs (business level). Partner labour is not a cost;
  external workers' pay is already an expense, so profit is correct as-is.
- Hours: (end - start - break) of work sessions, by start date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy.orm import Session

from app.db.models import (
    CustomerOrder,
    Expense,
    InventoryUpdate,
    InventoryUpdateItem,
    Work,
)

# --- time buckets -----------------------------------------------------------
TIME_GRANS = ("day", "week", "month", "quarter", "year")


def time_bucket(d: date, gran: str) -> str:
    if gran == "day":
        return d.isoformat()
    if gran == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if gran == "month":
        return f"{d.year}-{d.month:02d}"
    if gran == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if gran == "year":
        return str(d.year)
    raise ValueError(f"Invalid time granularity: {gran}")


def previous_period(start: date, end: date) -> tuple[date, date]:
    """The equally-long period immediately before [start, end]."""
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


# --- fact streams (generators) ---------------------------------------------
@dataclass
class Fact:
    when: date
    value: Decimal
    dims: dict  # dimension -> id (for scope filtering & dimension group-by)


def _color_shares(item) -> list[tuple[int | None, Decimal]]:
    """How to split an order item's value across its colours: by the entered
    percentages, else evenly; no colours -> a single (None) share of 1."""
    if not item.colors:
        return [(None, Decimal(1))]
    pcts = [(c.color_id, Decimal(c.color_percentage or 0)) for c in item.colors]
    total = sum((p for _, p in pcts), Decimal(0))
    if total > 0:
        return [(cid, p / total) for cid, p in pcts if p > 0]
    n = len(item.colors)
    return [(c.color_id, Decimal(1) / n) for c in item.colors]


def _revenue_facts(db: Session, start: date, end: date) -> list[Fact]:
    """Revenue attributed to order items (composition/colour), computed as
    (unit_price*qty + colour surcharges) * (1 - discount). This equals the order
    total_price line by line, and makes revenue breakable / filterable by
    composition, colour, location and customer. An item with no colours is a
    single (None-colour) fact; colour surcharges attach to their own colour.
    """
    facts: list[Fact] = []
    for o in _completed_orders(db, start, end):
        for it in o.items:
            keep = Decimal(1) - Decimal(it.discount or 0) / Decimal(100)
            base = Decimal(it.unit_price) * it.quantity * keep
            surcharge = {c.color_id: Decimal(c.color_surcharge or 0) * keep for c in it.colors}
            for color_id, share in _color_shares(it):
                value = base * share + surcharge.get(color_id, Decimal(0))
                facts.append(Fact(o.date, value, {
                    "composition": it.composition_id, "color": color_id,
                    "location": o.location_id, "customer": o.customer_party_id}))
    return facts


def _cost_facts(db: Session, start: date, end: date) -> list[Fact]:
    rows = db.query(Expense).filter(Expense.date >= start, Expense.date <= end).all()
    return [Fact(e.date, Decimal(e.total_cost), {"payee": e.paid_to_party_id}) for e in rows]


def _order_facts(db: Session, start: date, end: date) -> list[Fact]:
    rows = db.query(CustomerOrder).filter(
        CustomerOrder.state == "completed",
        CustomerOrder.date >= start, CustomerOrder.date <= end).all()
    return [Fact(o.date, Decimal(1), {"location": o.location_id}) for o in rows]


def _hours_facts(db: Session, start: date, end: date) -> list[Fact]:
    rows = db.query(Work).filter(Work.start_at.isnot(None), Work.end_at.isnot(None)).all()
    facts: list[Fact] = []
    for w in rows:
        d = w.start_at.date()
        if not (start <= d <= end):
            continue
        minutes = (w.end_at - w.start_at).total_seconds() / 60 - (w.break_minutes or 0)
        if minutes <= 0:
            continue
        facts.append(Fact(d, Decimal(str(round(minutes / 60, 4))), {"worker": w.party_id}))
    return facts


# --- item-level fact streams (composition dimension) ------------------------
def _completed_orders(db: Session, start: date, end: date):
    return db.query(CustomerOrder).filter(
        CustomerOrder.state == "completed",
        CustomerOrder.date >= start, CustomerOrder.date <= end).all()


def _items_sold_facts(db: Session, start: date, end: date) -> list[Fact]:
    """Composition units sold (order_item.quantity)."""
    facts: list[Fact] = []
    for o in _completed_orders(db, start, end):
        for it in o.items:
            facts.append(Fact(o.date, Decimal(it.quantity), {
                "composition": it.composition_id,
                "location": o.location_id, "customer": o.customer_party_id}))
    return facts


def _material_used_facts(db: Session, start: date, end: date) -> list[Fact]:
    """Pieces consumed by orders (inventory 'order_usage' lines, as a positive
    count), by colour and material. This is where the colour dimension lives."""
    rows = (db.query(InventoryUpdateItem, InventoryUpdate.date)
            .join(InventoryUpdate)
            .filter(InventoryUpdate.type == "order_usage",
                    InventoryUpdate.date >= start, InventoryUpdate.date <= end)
            .all())
    return [Fact(d, Decimal(-it.quantity_change),
                 {"color": it.color_id, "material": it.required_item_id})
            for it, d in rows if it.quantity_change < 0]


@dataclass
class BaseMetric:
    facts: Callable[[Session, date, date], list[Fact]]
    kind: str               # money | count | hours
    dims: tuple[str, ...]   # scope/group-by dimensions supported


BASE: dict[str, BaseMetric] = {
    "revenue": BaseMetric(_revenue_facts, "money", ("composition", "color", "location", "customer")),
    "costs": BaseMetric(_cost_facts, "money", ("payee",)),
    "orders": BaseMetric(_order_facts, "count", ("location",)),
    "hours": BaseMetric(_hours_facts, "hours", ("worker",)),
    "items_sold": BaseMetric(_items_sold_facts, "count", ("composition", "location", "customer")),
    "material_used": BaseMetric(_material_used_facts, "count", ("color", "material")),
}

# Composed metrics: (kind, group-by allowed only over time, no scope).
COMPOSED = {
    "profit": "money",
    "avg_order_value": "money",
    "revenue_per_hour": "money",
    "profit_per_hour": "money",
}
ALL_METRICS = {**{k: m.kind for k, m in BASE.items()}, **COMPOSED}


# --- operators --------------------------------------------------------------
def _apply_scope(facts: list[Fact], scope: dict | None) -> list[Fact]:
    """scope maps a dimension to a list of allowed ids (OR within a dim, AND
    across dims). A single id is also accepted for convenience."""
    if not scope:
        return facts

    def ok(f: Fact) -> bool:
        for k, v in scope.items():
            vals = v if isinstance(v, (list, tuple, set)) else (v,)
            if f.dims.get(k) not in vals:
                return False
        return True

    return [f for f in facts if ok(f)]


def _aggregate(facts: list[Fact], group_by: str | None):
    if group_by is None:
        return sum((f.value for f in facts), Decimal(0))
    out: dict = {}
    for f in facts:
        key = time_bucket(f.when, group_by) if group_by in TIME_GRANS else f.dims.get(group_by)
        out[key] = out.get(key, Decimal(0)) + f.value
    return out


def _combine(a, b, op, group_by: str | None):
    if group_by is None:
        return op(a, b)
    return {k: op(a.get(k, Decimal(0)), b.get(k, Decimal(0))) for k in set(a) | set(b)}


def _ratio(num, den, group_by: str | None):
    def one(a, b):
        return (a / b) if b else None
    if group_by is None:
        return one(num, den)
    return {k: one(num.get(k, Decimal(0)), den.get(k, Decimal(0))) for k in set(num) | set(den)}


# --- the single entry point -------------------------------------------------
def evaluate(db: Session, metric: str, start: date, end: date,
             group_by: str | None = None, scope: dict | None = None):
    """Scalar (group_by=None) or a {bucket_or_dim: value} series."""
    if metric in BASE:
        spec = BASE[metric]
        if group_by is not None and group_by not in TIME_GRANS and group_by not in spec.dims:
            raise ValueError(f"'{metric}' does not support grouping by '{group_by}'.")
        facts = _apply_scope(spec.facts(db, start, end), scope)
        return _aggregate(facts, group_by)

    # composed: business level (time group-by only, scope ignored)
    if group_by is not None and group_by not in TIME_GRANS:
        raise ValueError(f"Composed metric '{metric}' can only be grouped by time.")
    if metric == "profit":
        rev = evaluate(db, "revenue", start, end, group_by)
        cst = evaluate(db, "costs", start, end, group_by)
        return _combine(rev, cst, lambda a, b: a - b, group_by)
    if metric == "avg_order_value":
        return _ratio(evaluate(db, "revenue", start, end, group_by),
                      evaluate(db, "orders", start, end, group_by), group_by)
    if metric == "revenue_per_hour":
        return _ratio(evaluate(db, "revenue", start, end, group_by),
                      evaluate(db, "hours", start, end, group_by), group_by)
    if metric == "profit_per_hour":
        return _ratio(evaluate(db, "profit", start, end, group_by),
                      evaluate(db, "hours", start, end, group_by), group_by)
    raise ValueError(f"Unknown metric: {metric}")


def compare(db: Session, metric: str, start: date, end: date, scope: dict | None = None) -> dict:
    """Scalar current vs previous equal-length period, with delta and % change."""
    cur = evaluate(db, metric, start, end, None, scope)
    p_start, p_end = previous_period(start, end)
    prev = evaluate(db, metric, p_start, p_end, None, scope)
    delta = None if (cur is None or prev is None) else cur - prev
    pct = None
    if cur is not None and prev not in (None, 0, Decimal(0)):
        pct = round(float((cur - prev) / prev * 100), 1)
    return {"current": cur, "previous": prev, "delta": delta, "pct_change": pct,
            "previous_period": {"start": p_start.isoformat(), "end": p_end.isoformat()}}
