"""Read-only stock view.

Stock = SUM(inventory_update_item.quantity_change) grouped by
(required_item, color, variant), flagged against the effective minimum:
the most specific matching stock_threshold row, falling back to
required_item.minimum_safe_quantity.

On top of the current quantity each cell carries a forward-looking `level`
computed from the theoretical consumption of **confirmed** (not yet completed)
orders — the same BOM expansion used when an order is completed:

  * red    = stock won't cover the consumption of the next 10 days (goes < 0);
  * orange = after the next 10 days of consumption it drops below the minimum;
  * yellow = after ALL future consumption it drops below the minimum;
  * ok     = none of the above.

Severity hierarchy is red > orange > yellow (the first matching wins).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import (
    Color,
    CustomerOrder,
    InventoryUpdate,
    InventoryUpdateItem,
    RequiredItem,
    StockThreshold,
    User,
)
from app.db.session import get_db
from app.services.consumption import build_consumption

router = APIRouter(prefix="/api/stock", tags=["stock"])

FORECAST_HORIZON_DAYS = 10


class StockRow(BaseModel):
    required_item_id: int
    required_item_name: str
    unit: str
    color_id: int | None
    color_name: str | None
    variant: str | None
    quantity: int
    effective_minimum: int | None
    below_minimum: bool
    # forward-looking consumption from confirmed orders and the derived warning
    consume_next_10: int = 0   # units consumed within the next 10 days
    consume_future: int = 0    # units consumed by all future confirmed orders
    level: str = "ok"          # "red" | "orange" | "yellow" | "ok"


def _effective_minimum(
    thresholds: list[StockThreshold],
    item: RequiredItem,
    color_id: int | None,
    variant: str | None,
) -> int | None:
    """Most specific matching threshold wins; fall back to the item default.

    Specificity order: (color+variant) > (color) > (variant) > item default.
    """
    best = None
    best_score = -1
    for t in thresholds:
        if t.required_item_id != item.required_item_id:
            continue
        if t.color_id is not None and t.color_id != color_id:
            continue
        if t.variant is not None and t.variant != variant:
            continue
        score = (2 if t.color_id is not None else 0) + (1 if t.variant is not None else 0)
        if score > best_score:
            best, best_score = t.minimum_quantity, score
    if best is not None:
        return best
    return item.minimum_safe_quantity


def _cell_levels(db: Session) -> dict[tuple, int]:
    """Current derived stock per (required_item, color, variant).

    A **recount is an absolute checkpoint, not a delta**: it fixes the quantity at
    its date regardless of anything before it. So for each cell the current level
    is the LATEST recount's counted value plus only the non-recount movements that
    happened strictly AFTER it (by date, then entry order). A movement back-dated
    before the latest recount therefore cannot change today's stock. Cells with no
    recount fall back to the plain sum of all movements.
    """
    rows = (
        db.query(
            InventoryUpdateItem.required_item_id,
            InventoryUpdateItem.color_id,
            InventoryUpdateItem.variant,
            InventoryUpdateItem.quantity_change,
            InventoryUpdate.type,
            InventoryUpdate.date,
            InventoryUpdate.inventory_update_id,
        )
        .join(InventoryUpdate)
        .all()
    )
    cells: dict[tuple, list[tuple]] = defaultdict(list)
    for rid, cid, variant, qc, type_, d, uid in rows:
        cells[(rid, cid, variant)].append((d, uid, type_, int(qc)))

    levels: dict[tuple, int] = {}
    for cell, entries in cells.items():
        recounts = [(d, uid, qc) for (d, uid, type_, qc) in entries if type_ == "recount"]
        if recounts:
            rd, ruid, base = max(recounts, key=lambda e: (e[0], e[1]))
            levels[cell] = base + sum(
                qc for (d, uid, type_, qc) in entries
                if type_ != "recount" and (d, uid) > (rd, ruid))
        else:
            levels[cell] = sum(qc for (_, _, _, qc) in entries)
    return levels


def compute_stock(db: Session) -> list[StockRow]:
    """Derived stock rows (reused by the stock view and the dashboard)."""
    levels = _cell_levels(db)
    items = {i.required_item_id: i for i in db.query(RequiredItem).all()}
    colors = {c.color_id: c for c in db.query(Color).all()}
    thresholds = db.query(StockThreshold).all()

    # Materialise cells that have an explicit, cell-specific threshold but no
    # movements yet (quantity 0): a minimum set on an empty shelf must still raise
    # a "below minimum" warning instead of silently producing no row. Blanket
    # thresholds (colour AND digit both "any") are not a concrete cell, so skip
    # them — they only adjust the minimum of cells that already exist.
    for t in thresholds:
        if t.color_id is None and t.variant is None:
            continue
        levels.setdefault((t.required_item_id, t.color_id, t.variant), 0)

    rows: list[StockRow] = []
    for (item_id, color_id, variant), qty in levels.items():
        item = items[item_id]
        minimum = _effective_minimum(thresholds, item, color_id, variant)
        rows.append(StockRow(
            required_item_id=item_id,
            required_item_name=item.name,
            unit=item.unit,
            color_id=color_id,
            color_name=colors[color_id].name if color_id else None,
            variant=variant,
            quantity=int(qty),
            effective_minimum=minimum,
            below_minimum=minimum is not None and qty < minimum,
        ))
    rows.sort(key=lambda r: (r.required_item_name, r.color_name or "", r.variant or ""))
    return rows


def _forecast_consumption(
    db: Session, horizon: date,
) -> tuple[dict[tuple, int], dict[tuple, int]]:
    """Theoretical consumption of confirmed orders, per (item, color, variant).

    Returns (within_10_days, all_future). Reuses `build_consumption` but never
    persists it: the transient update objects are only read for their lines.
    Past-dated confirmed orders (not yet reconciled to 'completed') count toward
    the 10-day bucket too — their consumption is imminent/overdue.
    """
    consume_10: dict[tuple, int] = defaultdict(int)
    consume_all: dict[tuple, int] = defaultdict(int)
    confirmed = db.query(CustomerOrder).filter(CustomerOrder.state == "confirmed").all()
    for order in confirmed:
        update = build_consumption(db, order)
        if update is None:
            continue
        within = order.date <= horizon
        for line in update.items:
            qty = -int(line.quantity_change)   # consumption lines are negative
            if qty <= 0:
                continue
            key = (line.required_item_id, line.color_id, line.variant)
            consume_all[key] += qty
            if within:
                consume_10[key] += qty
    return consume_10, consume_all


def _warning_level(quantity: int, minimum: int | None, c10: int, c_all: int) -> str:
    """Red > orange > yellow > ok, first match wins (see module docstring)."""
    if quantity - c10 < 0:
        return "red"
    if minimum is not None and quantity - c10 < minimum:
        return "orange"
    if minimum is not None and quantity - c_all < minimum:
        return "yellow"
    return "ok"


def compute_stock_forecast(db: Session, today: date | None = None) -> list[StockRow]:
    """Current stock rows augmented with the forward-looking warning `level`.

    Cells with no current movements but with future consumption are added at
    quantity 0, so an impending shortage is never hidden just because the shelf
    is empty today.
    """
    today = today or date.today()
    horizon = today + timedelta(days=FORECAST_HORIZON_DAYS)
    rows = compute_stock(db)
    by_cell = {(r.required_item_id, r.color_id, r.variant): r for r in rows}

    consume_10, consume_all = _forecast_consumption(db, horizon)

    # Materialise forecast-only cells (future consumption, no stock row yet).
    missing = [k for k in consume_all if k not in by_cell]
    if missing:
        items = {i.required_item_id: i for i in db.query(RequiredItem).all()}
        colors = {c.color_id: c for c in db.query(Color).all()}
        thresholds = db.query(StockThreshold).all()
        for key in missing:
            ri_id, color_id, variant = key
            item = items.get(ri_id)
            if item is None:
                continue
            minimum = _effective_minimum(thresholds, item, color_id, variant)
            row = StockRow(
                required_item_id=ri_id, required_item_name=item.name, unit=item.unit,
                color_id=color_id, color_name=colors[color_id].name if color_id else None,
                variant=variant, quantity=0, effective_minimum=minimum,
                below_minimum=minimum is not None and 0 < minimum)
            by_cell[key] = row
            rows.append(row)

    for key, row in by_cell.items():
        row.consume_next_10 = consume_10.get(key, 0)
        row.consume_future = consume_all.get(key, 0)
        row.level = _warning_level(
            row.quantity, row.effective_minimum, row.consume_next_10, row.consume_future)

    rows.sort(key=lambda r: (r.required_item_name, r.color_name or "", r.variant or ""))
    return rows


@router.get("", response_model=list[StockRow])
def stock_view(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return compute_stock_forecast(db)