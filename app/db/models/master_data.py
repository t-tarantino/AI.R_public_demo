"""Master / informative tables (v2).

These hold reusable business entities and their *current / default* attributes.
Values here may change over time; historical facts live in the transactional
tables and are never recomputed from these.

Every column carries a `comment=` so the meaning is self-documenting both in the
code and in the database (PostgreSQL stores column comments; SQLite ignores them
but they remain here for future readers).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, String, Text
from sqlalchemy import false as sa_false
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Reusable column types ------------------------------------------------------
MONEY = Numeric(10, 2)     # currency amounts, never float


class Party(Base):
    """Unified anagraphic for every subject the business deals with: customers,
    suppliers and workers. One party can hold several roles at the same time
    (e.g. a shop that is both a supplier and, occasionally, a customer). The
    business itself is also a party, appearing as payer/payee on expenses.
    """

    __tablename__ = "party"

    party_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(200), comment="Display name / ragione sociale.")
    code_nickname: Mapped[str | None] = mapped_column(
        String(50), unique=True,
        comment="Short internal code (sigla), e.g. AMZ, FMG, AL. Unique when present.")
    is_customer: Mapped[bool] = mapped_column(
        default=False, comment="True if this party can place orders.")
    is_supplier: Mapped[bool] = mapped_column(
        default=False, comment="True if we buy goods/services from this party.")
    is_worker: Mapped[bool] = mapped_column(
        default=False, comment="True if this party performs work sessions / shares profits.")
    credit_hours: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), default=Decimal("0"), server_default="0",
        comment="Manual 'credit' hours for a worker, counted ONLY in the Time-page "
                "ranking board (never in money, profit, work totals or any other "
                "calculation). Lets a worker's ranking position be nudged for "
                "off-the-books contributions.")
    hidden_from_ranking: Mapped[bool] = mapped_column(
        default=False, server_default=sa_false(),
        comment="True hides this worker from the Time-page ranking board (and its "
                "credit-hours footer). Does not affect work sessions or any other "
                "calculation.")
    is_business: Mapped[bool] = mapped_column(
        default=False,
        comment="True for our own company (AI.R), the payer/payee entity distinct "
                "from the individual partner-workers. Lets the business be a party.")
    category: Mapped[str | None] = mapped_column(
        String(100),
        comment="Free grouping, mainly for suppliers, e.g. 'online', 'negozio fisico'.")
    phone: Mapped[str | None] = mapped_column(String(50), comment="Contact phone.")
    email: Mapped[str | None] = mapped_column(String(200), comment="Contact email.")
    website: Mapped[str | None] = mapped_column(String(300), comment="Website / shop URL.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    orders: Mapped[list["CustomerOrder"]] = relationship(back_populates="customer_party")  # noqa: F821
    work_entries: Mapped[list["Work"]] = relationship(back_populates="party")  # noqa: F821

    __table_args__ = (
        # A party must be something: at least one role flag has to be set.
        CheckConstraint(
            "is_customer OR is_supplier OR is_worker OR is_business", name="at_least_one_role"),
    )


class Location(Base):
    """Recurring/reusable venue where events take place (the areas of 'Riverside Hall')."""

    __tablename__ = "location"

    location_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), comment="Venue/area name, e.g. CHIC.")
    address: Mapped[str | None] = mapped_column(String(400), comment="Postal address.")
    phone: Mapped[str | None] = mapped_column(String(50), comment="Venue phone, if any.")
    email: Mapped[str | None] = mapped_column(String(200), comment="Venue email, if any.")
    active: Mapped[bool] = mapped_column(
        default=True, server_default=sa_true(),
        comment="False retires the venue from new orders, keeping its history.")
    comment: Mapped[str | None] = mapped_column(
        Text, comment="Notes, e.g. constraints like 'columns >200cm too tall here'.")

    orders: Mapped[list["CustomerOrder"]] = relationship(back_populates="location")  # noqa: F821


class Color(Base):
    """Conceptual balloon color (NOT a purchasable SKU)."""

    __tablename__ = "color"

    color_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, comment="Human color code, e.g. '045'. May change; unique.")
    name: Mapped[str] = mapped_column(String(100), comment="Color name, e.g. 'Rosso'.")
    type: Mapped[str | None] = mapped_column(
        String(50), comment="Optional family, e.g. 'normale', 'metal', 'perla'.")
    active: Mapped[bool] = mapped_column(
        default=True, comment="False hides the color from new orders without deleting history.")
    in_catalog: Mapped[bool] = mapped_column(
        default=True,
        comment="True = standard palette color. False = special/off-catalog color: "
                "its use adds a surcharge (recorded on order_item_color.color_surcharge).")
    swatch_hex: Mapped[str | None] = mapped_column(
        String(7),
        comment="Optional display colour for the swatch in Stock/Products, as '#rrggbb'. "
                "When NULL the UI falls back to the built-in palette hex (by code) or grey.")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    products: Mapped[list["Product"]] = relationship(back_populates="color")  # noqa: F821


class Composition(Base):
    """A sellable balloon composition (the price-list item)."""

    __tablename__ = "composition"

    composition_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True,
        comment="Human catalogue code, e.g. '001', '05S', 'P01', 'NME'. TEXT, unique.")
    name: Mapped[str] = mapped_column(String(200), comment="Display name.")
    standard_price: Mapped[Decimal] = mapped_column(
        MONEY,
        comment="CURRENT default price. Historical sale price lives in order_item.unit_price.")
    estimated_working_time: Mapped[int | None] = mapped_column(
        comment="Rough build time in minutes, for planning. Nullable.")
    active: Mapped[bool] = mapped_column(
        default=True, comment="False retires the item from new orders, keeping history.")
    comment: Mapped[str | None] = mapped_column(
        Text, comment="Notes, e.g. 'price per digit', combo contents/free gifts.")

    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        back_populates="composition", cascade="all, delete-orphan")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="composition")  # noqa: F821

    __table_args__ = (
        CheckConstraint("standard_price >= 0", name="standard_price_non_negative"),
    )


class ExpenseCategory(Base):
    """Controlled vocabulary of expense categories (the fixed drop-down list)."""

    __tablename__ = "expense_category"

    expense_category_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(100), unique=True,
        comment="Category name, e.g. 'materials', 'transport'. Unique.")

    expense_items: Mapped[list["ExpenseItem"]] = relationship(back_populates="category")  # noqa: F821