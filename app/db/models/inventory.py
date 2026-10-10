"""Inventory tables (v2): inventory_update (header) + inventory_update_item (lines).

Stock is tracked at the REQUIRED_ITEM level (not per product), but split by
COLOR for colored materials, and by an optional VARIANT (e.g. the digit for
number balloons). Current stock is DERIVED, never stored:

    SELECT required_item_id, color_id, variant, SUM(quantity_change)
    FROM inventory_update_item
    GROUP BY required_item_id, color_id, variant;

A purchase of a product raises the stock of its required_item
(product.required_item_id). See docs/data_model_v2.md for the parked
delta-vs-snapshot discussion.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Controlled vocabulary for movement reasons.
#  purchase / order_usage  -> generated automatically (expense refill / order consumption)
#  recount / loss / gift    -> manual stock updates (recount=absolute, loss=-, gift=+)
MOVEMENT_TYPES = ("purchase", "order_usage", "recount", "loss", "gift")


class InventoryUpdate(Base):
    """A single stock-change document (header) grouping one or more lines."""

    __tablename__ = "inventory_update"

    inventory_update_id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(
        String(30),
        comment="Reason: purchase | order_usage | damage | correction.")
    date: Mapped[date] = mapped_column(Date, comment="When the change happened.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    items: Mapped[list["InventoryUpdateItem"]] = relationship(
        back_populates="update", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(f"type IN {MOVEMENT_TYPES}", name="movement_type_valid"),
    )


class InventoryUpdateItem(Base):
    """One stock change for one required_item (signed delta)."""

    __tablename__ = "inventory_update_item"

    inventory_update_item_id: Mapped[int] = mapped_column(primary_key=True)
    inventory_update_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_update.inventory_update_id"), comment="Parent document.")
    required_item_id: Mapped[int] = mapped_column(
        ForeignKey("required_item.required_item_id"),
        comment="The material whose stock changes (stock lives at this level).")
    color_id: Mapped[int | None] = mapped_column(
        ForeignKey("color.color_id"),
        comment="Color of the stock affected, for colored materials. NULL if the item has no color.")
    variant: Mapped[str | None] = mapped_column(
        String(20),
        comment="Optional sub-variant within the material, e.g. the digit '0'..'9' for number balloons.")
    quantity_change: Mapped[int] = mapped_column(
        comment="For delta movements (purchase/order_usage/loss/gift): a signed "
                "change (+ in, - out). For a RECOUNT row (parent type='recount') it "
                "instead holds the counted ABSOLUTE quantity at that date — a "
                "checkpoint the stock derivation rebases on. May be 0 (empty recount).")
    expense_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("expense_item.expense_item_id"),
        comment="Provenance: the purchase line that caused a +N. Nullable.")
    customer_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_order.customer_order_id"),
        comment="Provenance: the order that consumed a -N. Nullable.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    update: Mapped["InventoryUpdate"] = relationship(back_populates="items")
    required_item: Mapped["RequiredItem"] = relationship(back_populates="inventory_lines")  # noqa: F821
    color: Mapped["Color | None"] = relationship()  # noqa: F821

    # No non-zero constraint: a recount row legitimately stores an absolute 0 (empty).