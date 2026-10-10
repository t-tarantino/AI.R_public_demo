"""Expense tables (v2): expense, expense_item.

An expense is a money flow between two parties (paid_by -> paid_to). Worker pay
(profit split) is just an expense paid to a worker-party, so labour cost is a
correct historical fact with no wage recomputation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MONEY = Numeric(10, 2)


class Expense(Base):
    """One expense/payment event between two parties."""

    __tablename__ = "expense"

    expense_id: Mapped[int] = mapped_column(primary_key=True)
    paid_by_party_id: Mapped[int] = mapped_column(
        ForeignKey("party.party_id"), comment="Party that paid (usually the business).")
    paid_to_party_id: Mapped[int] = mapped_column(
        ForeignKey("party.party_id"), comment="Party that received the money (supplier/worker).")
    date: Mapped[date] = mapped_column(Date, comment="Payment date.")
    total_cost: Mapped[Decimal] = mapped_column(
        MONEY, comment="Actual total amount paid in this transaction.")
    payment_method: Mapped[str | None] = mapped_column(
        String(50), comment="e.g. 'card', 'cash', 'transfer'. Nullable.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    paid_by: Mapped["Party"] = relationship(foreign_keys=[paid_by_party_id])  # noqa: F821
    paid_to: Mapped["Party"] = relationship(foreign_keys=[paid_to_party_id])  # noqa: F821
    items: Mapped[list["ExpenseItem"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("total_cost >= 0", name="total_cost_non_negative"),
        CheckConstraint(
            "paid_by_party_id <> paid_to_party_id", name="payer_differs_from_payee"),
    )


class ExpenseItem(Base):
    """One line within an expense. May reference a product bought and/or an order
    the cost is attributed to. Lines without a product (parking, fuel) are fine."""

    __tablename__ = "expense_item"

    expense_item_id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(
        ForeignKey("expense.expense_id"), comment="Parent expense.")
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.product_id"),
        comment="Product purchased on this line. NULL for non-product costs.")
    customer_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_order.customer_order_id"),
        comment="Order this cost is attributed to, if any. Nullable.")
    expense_category_id: Mapped[int] = mapped_column(
        ForeignKey("expense_category.expense_category_id"),
        comment="Category from the controlled list.")
    description: Mapped[str | None] = mapped_column(
        String(300), comment="Short free description of the line. Nullable.")
    variant: Mapped[str | None] = mapped_column(
        String(20),
        comment="Digit ('0'..'9') for number-balloon purchases; drives the stock "
                "variant on refill. NULL for everything else.")
    quantity: Mapped[int] = mapped_column(comment="Quantity bought (> 0).")
    unit_cost: Mapped[Decimal] = mapped_column(
        MONEY, comment="HISTORICAL purchase cost per unit (snapshot; never recomputed).")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    expense: Mapped["Expense"] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship(back_populates="expense_items")  # noqa: F821
    category: Mapped["ExpenseCategory"] = relationship(back_populates="expense_items")  # noqa: F821
    order: Mapped["CustomerOrder | None"] = relationship()  # noqa: F821

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="unit_cost_non_negative"),
    )