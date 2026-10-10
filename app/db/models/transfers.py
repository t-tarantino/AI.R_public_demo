"""Money transfer: a plain cash movement between two parties.

Unlike `expense` (always a business cost, someone paying a supplier/worker on
the business's behalf) and `customer_order` (always business revenue), a
transfer is NOT tied to a purchase or a sale. It exists purely to record "party
A gave party B this amount of money", most often to settle a debt that arose
from an expense (reimbursement) or an order (customer payment). It is a fully
generic ledger row: any two parties, business or not, can be on either side.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MONEY = Numeric(10, 2)


class MoneyTransfer(Base):
    """One cash movement: `from_party` gave `to_party` `amount` on `date`.

    Historical fact, never recomputed. Feeds the money-balance calculation
    alongside expenses (fronted costs) and orders (customer revenue): see
    `app.services.metrics.money_balances`.
    """

    __tablename__ = "money_transfer"

    money_transfer_id: Mapped[int] = mapped_column(primary_key=True)
    from_party_id: Mapped[int] = mapped_column(
        ForeignKey("party.party_id"), comment="Party that gave the money.")
    to_party_id: Mapped[int] = mapped_column(
        ForeignKey("party.party_id"), comment="Party that received the money.")
    date: Mapped[date] = mapped_column(Date, comment="Date the transfer happened.")
    amount: Mapped[Decimal] = mapped_column(MONEY, comment="Amount moved (> 0).")
    payment_method: Mapped[str | None] = mapped_column(
        String(50), comment="e.g. 'card', 'cash', 'transfer'. Nullable.")
    comment: Mapped[str | None] = mapped_column(
        Text, comment="Free-text notes, e.g. what debt this settles.")

    from_party: Mapped["Party"] = relationship(foreign_keys=[from_party_id])  # noqa: F821
    to_party: Mapped["Party"] = relationship(foreign_keys=[to_party_id])  # noqa: F821

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("from_party_id <> to_party_id", name="from_differs_from_to"),
    )
