"""Order tables (v2): customer_order, order_item, order_item_color.

Rows are historical facts. Snapshot values (unit_price, discount) must never be
recomputed from current master data.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MONEY = Numeric(10, 2)
PERCENT = Numeric(5, 2)

# Controlled vocabularies (kept small and explicit; enforced by CHECK).
ORDER_STATES = ("draft", "confirmed", "completed", "cancelled")
GENDERS = ("M", "F", "altro")


class CustomerOrder(Base):
    """One customer order / event. Named `customer_order` (also avoids the
    reserved word `order`)."""

    __tablename__ = "customer_order"

    customer_order_id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("location.location_id"), comment="Where the event takes place.")
    customer_party_id: Mapped[int | None] = mapped_column(
        ForeignKey("party.party_id"),
        comment="Who ordered. Usually NULL (the location is the client); ready for the future.")
    state: Mapped[str] = mapped_column(
        String(20), default="draft",
        comment="Order lifecycle: draft | confirmed | completed | cancelled.")
    event_type: Mapped[str | None] = mapped_column(
        String(50),
        comment="Kind of event, e.g. 'compleanno', 'matrimonio'. Free text for now.")
    celebrated_age: Mapped[int | None] = mapped_column(
        comment="Age being celebrated (birthdays), if relevant. Nullable.")
    celebrant_gender: Mapped[str | None] = mapped_column(
        String(10), comment="Gender of the celebrant: M | F | altro. Nullable.")
    date: Mapped[date] = mapped_column(Date, comment="Event date.")
    total_price: Mapped[Decimal] = mapped_column(
        MONEY, comment="Actual total customer-facing price (NOT a cost).")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    location: Mapped["Location"] = relationship(back_populates="orders")  # noqa: F821
    customer_party: Mapped["Party | None"] = relationship(back_populates="orders")  # noqa: F821
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan")
    work_sessions: Mapped[list["Work"]] = relationship(  # noqa: F821
        secondary="work_order", back_populates="orders")

    __table_args__ = (
        CheckConstraint("total_price >= 0", name="total_price_non_negative"),
        CheckConstraint(
            f"state IN {ORDER_STATES}", name="state_valid"),
        CheckConstraint(
            f"celebrant_gender IS NULL OR celebrant_gender IN {GENDERS}",
            name="celebrant_gender_valid"),
        CheckConstraint(
            "celebrated_age IS NULL OR celebrated_age >= 0",
            name="celebrated_age_non_negative"),
    )


class OrderItem(Base):
    """One composition sold inside an order."""

    __tablename__ = "order_item"

    order_item_id: Mapped[int] = mapped_column(primary_key=True)
    customer_order_id: Mapped[int] = mapped_column(
        ForeignKey("customer_order.customer_order_id"), comment="Parent order.")
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("composition.composition_id"), comment="What was sold.")
    quantity: Mapped[int] = mapped_column(comment="Units sold (> 0).")
    unit_price: Mapped[Decimal] = mapped_column(
        MONEY, comment="HISTORICAL sale price per unit (snapshot at sale time).")
    discount: Mapped[Decimal | None] = mapped_column(
        PERCENT, comment="Line discount in percent (0..100). Nullable.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    order: Mapped["CustomerOrder"] = relationship(back_populates="items")
    composition: Mapped["Composition"] = relationship(back_populates="order_items")  # noqa: F821
    colors: Mapped[list["OrderItemColor"]] = relationship(
        back_populates="order_item", cascade="all, delete-orphan")
    numbers: Mapped[list["OrderItemNumber"]] = relationship(
        back_populates="order_item", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(
            "discount IS NULL OR (discount >= 0 AND discount <= 100)", name="discount_range"),
    )


class OrderItemNumber(Base):
    """One foil number balloon used in a sold line: a digit, in a colour and size.

    e.g. an age '18' on a 'Nuvoletta con numero' is two rows (digit 1, digit 8).
    Number colours are independent of the item's balloon colour mix; the default
    is silver (gold when the item's balloon mix includes gold). Size defaults to
    the composition's number requirement but is editable.
    """

    __tablename__ = "order_item_number"

    order_item_number_id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_item.order_item_id"), comment="The sold line this number belongs to.")
    required_item_id: Mapped[int] = mapped_column(
        ForeignKey("required_item.required_item_id"),
        comment="The number material/size used (e.g. 'Palloncino numero 80').")
    color_id: Mapped[int] = mapped_column(
        ForeignKey("color.color_id"),
        comment="Number colour (independent; default silver, gold if the mix has gold).")
    digit: Mapped[str] = mapped_column(
        String(1), comment="The digit shown, '0'..'9'.")
    quantity: Mapped[int] = mapped_column(
        default=1, server_default="1", comment="How many of this digit/colour/size (> 0).")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    order_item: Mapped["OrderItem"] = relationship(back_populates="numbers")
    required_item: Mapped["RequiredItem"] = relationship()  # noqa: F821
    color: Mapped["Color"] = relationship()  # noqa: F821

    __table_args__ = (
        CheckConstraint("quantity > 0", name="oin_quantity_positive"),
        CheckConstraint("digit >= '0' AND digit <= '9'", name="oin_digit_valid"),
    )


class OrderItemColor(Base):
    """One color used in one specific sold composition (references order_item)."""

    __tablename__ = "order_item_color"

    order_item_color_id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_item.order_item_id"), comment="The sold line this color belongs to.")
    color_id: Mapped[int] = mapped_column(
        ForeignKey("color.color_id"), comment="The color used.")
    color_percentage: Mapped[Decimal | None] = mapped_column(
        PERCENT, comment="Share of this color in the item (0..100). Nullable.")
    color_surcharge: Mapped[Decimal] = mapped_column(
        MONEY, default=Decimal("0"),
        comment="HISTORICAL surcharge (€) charged for using THIS color on THIS line "
                "(0 if none). Typically > 0 when the color is off-catalog. Snapshot; "
                "never recomputed.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    order_item: Mapped["OrderItem"] = relationship(back_populates="colors")
    color: Mapped["Color"] = relationship()  # noqa: F821

    __table_args__ = (
        UniqueConstraint("order_item_id", "color_id", name="order_item_color_unique"),
        CheckConstraint(
            "color_percentage IS NULL OR (color_percentage >= 0 AND color_percentage <= 100)",
            name="color_percentage_range"),
        CheckConstraint("color_surcharge >= 0", name="color_surcharge_non_negative"),
    )