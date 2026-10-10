"""Generate theoretical inventory consumption when an order is completed.

For each order item, expand the composition BOM (requirements) into inventory
movements at the (required_item, color) level:

    needed = requirement.quantity * order_item.quantity

If the required_item uses colour, `needed` is split across the order item's
colours: by the entered percentages when present, otherwise EVENLY across the
listed colours (2 colours -> 50/50, 3 -> 34/33/33, ...). Following the design
docs' v1 limitation, the SAME colour mix applies to every coloured requirement
of the item. Rounding uses the largest-remainder method so the per-colour
integers sum back to `needed`.

Number materials (required_item.is_number) are the exception: they are NOT taken
from the BOM colour split but from the per-order `order_item_number` detail, so
each consumed number carries its own size, colour and digit (variant). Those rows
are always present by consumption time: an order line on a number composition that
was saved without digits is filled at build time with the default "18" (see
`default_numbers`, applied by both manual entry and the Richie importer).

The result is one `inventory_update` of type 'order_usage' whose lines carry
negative `quantity_change` and reference the order for provenance.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import CustomerOrder, InventoryUpdate, InventoryUpdateItem

# Default foil number when an order line uses a number composition but no digit
# is given: "18" (the most common age), i.e. digits 1 and 8, cycling to fill as
# many number balloons as the composition's BOM needs. Applied at order-build
# time (visible and editable), for both manual entry and the Richie importer.
DEFAULT_DIGITS = ("1", "8")


def number_requirements(composition) -> list:
    """The composition's requirements that are foil numbers (is_number material)."""
    return [r for r in composition.requirements if r.required_item.is_number]


def default_numbers(composition, item_quantity: int, color_id: int) -> list[tuple[int, str, int, int]]:
    """Default (required_item_id, digit, quantity, color_id) rows for a number
    composition saved without explicit numbers — digits 1 and 8, one set per
    number requirement, scaled by the order line quantity."""
    out: list[tuple[int, str, int, int]] = []
    for req in number_requirements(composition):
        needed = int((req.quantity * item_quantity).to_integral_value(rounding="ROUND_HALF_UP"))
        per_digit: dict[str, int] = {}
        for k in range(needed):
            d = DEFAULT_DIGITS[k % len(DEFAULT_DIGITS)]
            per_digit[d] = per_digit.get(d, 0) + 1
        for digit, cnt in per_digit.items():
            out.append((req.required_item_id, digit, cnt, color_id))
    return out


def _split_by_colours(total: int, colours: list[tuple[int, Decimal]]) -> dict[int, int]:
    """Split `total` units across colours by percentage (largest remainder)."""
    if not colours:
        return {}
    raw = {cid: (Decimal(total) * pct / Decimal(100)) for cid, pct in colours}
    floored = {cid: int(v) for cid, v in raw.items()}
    # Clamp defensively: percentages should sum to <=100 (enforced on input), so
    # remainder is normally >=0. If bad data ever pushes it negative, a negative
    # slice below would silently mis-distribute, so we floor it at 0.
    remainder = max(total - sum(floored.values()), 0)
    # distribute the remaining units to the largest fractional parts
    order = sorted(colours, key=lambda c: (raw[c[0]] - floored[c[0]]), reverse=True)
    for cid, _ in order[:remainder]:
        floored[cid] += 1
    return floored


def build_consumption(db: Session, order: CustomerOrder) -> InventoryUpdate | None:
    """Build (but do not commit) the order_usage inventory update for an order.

    Returns None if the order consumes nothing (no BOM on its compositions).
    """
    update = InventoryUpdate(type="order_usage", date=order.date,
                             comment=f"Theoretical consumption, order #{order.customer_order_id}")
    any_line = False

    for item in order.items:
        color_ids = [c.color_id for c in item.colors]
        has_pct = any((c.color_percentage or Decimal(0)) > 0 for c in item.colors)
        # Use the entered proportions when present; otherwise split the item's
        # colours evenly (2 colours -> 50/50, 3 -> 34/33/33, and so on).
        if has_pct:
            colours = [(c.color_id, c.color_percentage or Decimal(0)) for c in item.colors]
        elif color_ids:
            even = Decimal(100) / Decimal(len(color_ids))
            colours = [(cid, even) for cid in color_ids]
        else:
            colours = []

        for req in item.composition.requirements:
            # Numbers are consumed from the per-order detail, not the BOM.
            if req.required_item.is_number:
                continue
            needed = int((req.quantity * item.quantity).to_integral_value(rounding="ROUND_HALF_UP"))
            if needed <= 0:
                continue
            if req.required_item.used_color and colours:
                for color_id, qty in _split_by_colours(needed, colours).items():
                    if qty <= 0:
                        continue
                    update.items.append(InventoryUpdateItem(
                        required_item_id=req.required_item_id, color_id=color_id,
                        quantity_change=-qty, customer_order_id=order.customer_order_id))
                    any_line = True
            else:
                update.items.append(InventoryUpdateItem(
                    required_item_id=req.required_item_id,
                    quantity_change=-needed, customer_order_id=order.customer_order_id))
                any_line = True

        # Numbers are consumed from the per-order detail (each carries its own
        # size, colour and digit). Nothing is invented: an order with a number
        # composition but no detail can't be completed (guarded in orders_api).
        for num in item.numbers:
            update.items.append(InventoryUpdateItem(
                required_item_id=num.required_item_id, color_id=num.color_id,
                variant=num.digit, quantity_change=-num.quantity,
                customer_order_id=order.customer_order_id))
            any_line = True

    return update if any_line else None


def order_already_consumed(db: Session, order_id: int) -> bool:
    """True if an order_usage update for this order already exists."""
    return db.query(InventoryUpdateItem).filter(
        InventoryUpdateItem.customer_order_id == order_id
    ).join(InventoryUpdate).filter(InventoryUpdate.type == "order_usage").first() is not None


def _consumption_updates(db: Session, order_id: int) -> list[InventoryUpdate]:
    """The order_usage movement(s) generated by this order."""
    return (db.query(InventoryUpdate)
            .join(InventoryUpdateItem,
                  InventoryUpdateItem.inventory_update_id == InventoryUpdate.inventory_update_id)
            .filter(InventoryUpdate.type == "order_usage",
                    InventoryUpdateItem.customer_order_id == order_id)
            .distinct().all())


def delete_consumption(db: Session, order_id: int) -> None:
    """Remove the order's theoretical consumption (so it can be rebuilt)."""
    for update in _consumption_updates(db, order_id):
        db.delete(update)
    db.flush()


def sync_consumption_date(db: Session, order: CustomerOrder) -> None:
    """Keep the consumption movement's date aligned with the order date."""
    for update in _consumption_updates(db, order.customer_order_id):
        update.date = order.date