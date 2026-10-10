"""Bill-of-materials tables (v2): required_item, requirements, product.

Three layers:
  * required_item  = the ABSTRACT material a composition needs (e.g. "large
                     balloon"). Stock and reorder threshold live here.
  * requirements   = how many of a required_item a composition needs (M:N).
  * product        = a CONCRETE purchasable SKU (a specific source/link) that
                     satisfies a required_item, optionally in a color.

Inventory is tracked at the required_item level (see inventory.py); several
products from different sources can satisfy the same required_item.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

QTY = Numeric(10, 2)  # quantities may be fractional (e.g. kg, lt)


class RequiredItem(Base):
    """An abstract material needed to build compositions. The unit of stock."""

    __tablename__ = "required_item"

    required_item_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(200), comment="Material name, e.g. 'Palloncino grande', 'Nastro'.")
    type: Mapped[str | None] = mapped_column(
        String(100), comment="Optional category of material, e.g. 'balloon', 'structure'.")
    dimension: Mapped[str | None] = mapped_column(
        String(100), comment="Size/format if relevant, e.g. '30cm'. Nullable.")
    unit: Mapped[str] = mapped_column(
        String(30),
        comment="Unit of measure used for quantities/stock: 'piece', 'kg', 'lt', etc.")
    used_color: Mapped[bool] = mapped_column(
        default=False,
        comment="True if this material comes in colors (so products specify a color).")
    is_number: Mapped[bool] = mapped_column(
        default=False, server_default="0",
        comment="True for foil number balloons (0-9). Their digit/colour/size are "
                "chosen per order (order_item_number), not from the composition colour mix.")
    minimum_safe_quantity: Mapped[int | None] = mapped_column(
        comment="Reorder threshold in `unit`. Alerts when stock falls below. Nullable.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    requirements: Mapped[list["Requirement"]] = relationship(back_populates="required_item")
    products: Mapped[list["Product"]] = relationship(back_populates="required_item")
    inventory_lines: Mapped[list["InventoryUpdateItem"]] = relationship(  # noqa: F821
        back_populates="required_item")
    thresholds: Mapped[list["StockThreshold"]] = relationship(back_populates="required_item")

    __table_args__ = (
        CheckConstraint(
            "minimum_safe_quantity IS NULL OR minimum_safe_quantity >= 0",
            name="minimum_safe_quantity_non_negative"),
    )


class Requirement(Base):
    """Junction: how much of a required_item a composition consumes."""

    __tablename__ = "requirements"

    requirement_id: Mapped[int] = mapped_column(primary_key=True)
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("composition.composition_id"),
        comment="The composition that needs the material.")
    required_item_id: Mapped[int] = mapped_column(
        ForeignKey("required_item.required_item_id"),
        comment="The material needed.")
    quantity: Mapped[Decimal] = mapped_column(
        QTY, comment="How many `unit` of the required_item this composition needs (> 0).")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    composition: Mapped["Composition"] = relationship(back_populates="requirements")  # noqa: F821
    required_item: Mapped["RequiredItem"] = relationship(back_populates="requirements")

    __table_args__ = (
        UniqueConstraint("composition_id", "required_item_id", name="requirement_unique"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


class Product(Base):
    """A concrete purchasable SKU that satisfies a required_item."""

    __tablename__ = "product"

    product_id: Mapped[int] = mapped_column(primary_key=True)
    required_item_id: Mapped[int] = mapped_column(
        ForeignKey("required_item.required_item_id"),
        comment="Which abstract material this product provides.")
    color_id: Mapped[int | None] = mapped_column(
        ForeignKey("color.color_id"),
        comment="Color of this SKU, if the material uses colors. Nullable.")
    variant: Mapped[str | None] = mapped_column(
        String(20),
        comment="Variant this SKU is for, e.g. the digit '1'/'8' of a foil number. "
                "NULL for materials without a per-variant SKU (most products). Together "
                "with (required_item_id, color_id) it identifies the exact stock cell "
                "this product refills.")
    product_code: Mapped[str | None] = mapped_column(
        String(100), comment="Supplier/internal product code. Nullable.")
    product_link: Mapped[str | None] = mapped_column(
        String(500), comment="URL where the product can be (re)ordered. Nullable.")
    is_first_choice: Mapped[bool] = mapped_column(
        default=False, server_default=sa_false(),
        comment="True = the preferred product to (re)order for its exact stock cell "
                "(required_item_id + color_id + variant). The Stock page '+' buy button "
                "opens this product's link. At most one per cell (enforced in the API).")
    name: Mapped[str] = mapped_column(
        String(200), comment="Product label, e.g. 'Palloncino lattice 30cm rosso'.")
    package_quantity: Mapped[int] = mapped_column(
        default=1, server_default="1",
        comment="Pieces per purchased unit (pack size). Stock refill multiplies the "
                "expense quantity by this, so buying 2 packs of 100 adds 200. 1 = per piece.")
    default_price: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        comment="Usual cost per PURCHASED unit (pack), same unit as expense_item.unit_cost. "
                "Nullable. Only a convenience default + sanity-check: pre-fills expense entry "
                "and flags a diff when the entered cost differs. Never overrides the frozen "
                "historical unit_cost, and is not auto-updated from purchases.")
    active: Mapped[bool] = mapped_column(
        default=True, comment="False retires the SKU (e.g. no longer sold) without losing history.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    required_item: Mapped["RequiredItem"] = relationship(back_populates="products")
    color: Mapped["Color | None"] = relationship(back_populates="products")  # noqa: F821
    expense_items: Mapped[list["ExpenseItem"]] = relationship(back_populates="product")  # noqa: F821

    __table_args__ = (
        CheckConstraint("package_quantity > 0", name="package_quantity_positive"),
        CheckConstraint("default_price IS NULL OR default_price >= 0",
                        name="default_price_non_negative"),
    )


class StockThreshold(Base):
    """Reorder threshold for a SPECIFIC color/variant of a required_item.

    The general default lives on `required_item.minimum_safe_quantity`; a row
    here overrides it for a specific color and/or variant. The effective minimum
    for a (required_item, color, variant) is the most specific matching row,
    falling back to the required_item default.
    """

    __tablename__ = "stock_threshold"

    stock_threshold_id: Mapped[int] = mapped_column(primary_key=True)
    required_item_id: Mapped[int] = mapped_column(
        ForeignKey("required_item.required_item_id"), comment="Material this threshold is for.")
    color_id: Mapped[int | None] = mapped_column(
        ForeignKey("color.color_id"),
        comment="Color it applies to. NULL = any color.")
    variant: Mapped[str | None] = mapped_column(
        String(20),
        comment="Variant it applies to, e.g. digit '1'. NULL = any variant.")
    minimum_quantity: Mapped[int] = mapped_column(
        comment="Reorder threshold for this specific combination (>= 0).")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    required_item: Mapped["RequiredItem"] = relationship(back_populates="thresholds")
    color: Mapped["Color | None"] = relationship()  # noqa: F821

    __table_args__ = (
        UniqueConstraint("required_item_id", "color_id", "variant", name="stock_threshold_unique"),
        CheckConstraint("minimum_quantity >= 0", name="minimum_quantity_non_negative"),
    )