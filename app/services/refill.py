"""Generate stock refill when an expense buys products.

Each expense line that references a product (`expense_item.product_id`) is a
purchase of that product's material, in that product's colour. We turn it into a
positive `purchase` inventory movement at the (required_item, colour) level,
carrying the expense line as provenance.

Lines without a product (parking, fuel, software…) buy no stock and are ignored.

Note: the movement lands at material+colour granularity. Products carry no digit
(`variant`), so number-balloon purchases are not split per digit — that split
belongs to the number-detail model (Fase 3).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import (
    Expense,
    ExpenseItem,
    InventoryUpdate,
    InventoryUpdateItem,
    Product,
)


def build_refill(db: Session, expense: Expense) -> InventoryUpdate | None:
    """Build (but do not commit) the purchase inventory update for an expense.

    Returns None if the expense buys no product (nothing to add to stock).
    """
    update = InventoryUpdate(
        type="purchase", date=expense.date,
        comment=f"Refill from expense #{expense.expense_id}")
    any_line = False

    for item in expense.items:
        if item.product_id is None:
            continue
        product = db.get(Product, item.product_id)
        if product is None:
            continue
        # Expenses are recorded in purchased units (packs); stock is in pieces.
        pieces = item.quantity * (product.package_quantity or 1)
        update.items.append(InventoryUpdateItem(
            required_item_id=product.required_item_id,
            color_id=product.color_id,
            variant=item.variant,               # digit for number balloons, else NULL
            quantity_change=pieces,             # positive = stock in
            expense_item_id=item.expense_item_id))
        any_line = True

    return update if any_line else None


def expense_already_refilled(db: Session, expense_id: int) -> bool:
    """True if any purchase movement already references a line of this expense."""
    return (db.query(InventoryUpdateItem)
            .join(ExpenseItem,
                  InventoryUpdateItem.expense_item_id == ExpenseItem.expense_item_id)
            .filter(ExpenseItem.expense_id == expense_id)
            .first() is not None)


def _refills_of(db: Session, expense: Expense) -> list[InventoryUpdate]:
    """The purchase movement(s) generated from this expense (via line provenance).

    Relies on the current expense.items still carrying their ids, so call it
    before the items are cleared/replaced.
    """
    item_ids = [it.expense_item_id for it in expense.items if it.expense_item_id]
    if not item_ids:
        return []
    return (db.query(InventoryUpdate)
            .join(InventoryUpdateItem,
                  InventoryUpdateItem.inventory_update_id == InventoryUpdate.inventory_update_id)
            .filter(InventoryUpdateItem.expense_item_id.in_(item_ids))
            .distinct().all())


def delete_refill(db: Session, expense: Expense) -> None:
    """Delete the expense's purchase movement(s), freeing the FK on its items.

    Must run while the expense items still exist. Cascades to the movement lines
    (which are what reference expense_item), so the items can then be replaced.
    """
    for update in _refills_of(db, expense):
        db.delete(update)
    db.flush()


def sync_refill_date(db: Session, expense: Expense) -> None:
    """Keep the purchase movement's date aligned with the expense date."""
    for update in _refills_of(db, expense):
        update.date = expense.date