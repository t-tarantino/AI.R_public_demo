"""Work table (v2): one row = one work session/activity.

Work tracks TIME and ACTIVITY only. It carries no wage/cost: worker pay is a
profit split recorded as `expense` rows (already a correct historical fact).
Duration is derived from start/end minus break; see docs/data_model_v2.md for
the parked option of storing an explicit duration.

A session can relate to SEVERAL orders at once: a work shift usually covers all
the compositions built that day, across locations. The link is therefore
many-to-many via `work_order`. A session with no links is general internal work;
a day with a single order is just the 1:1 special case.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Association table: which orders a work session covers (M:N).
work_order = Table(
    "work_order",
    Base.metadata,
    Column("work_id", ForeignKey("work.work_id"), primary_key=True),
    Column("customer_order_id", ForeignKey("customer_order.customer_order_id"),
           primary_key=True),
)


class Work(Base):
    __tablename__ = "work"

    work_id: Mapped[int] = mapped_column(primary_key=True)
    party_id: Mapped[int] = mapped_column(
        ForeignKey("party.party_id"),
        comment="The worker (a party with is_worker = true) who did the session.")
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="Session start (date + time). Nullable.")
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="Session end (date + time). Nullable.")
    break_minutes: Mapped[int | None] = mapped_column(
        comment="Unpaid break within the session, in minutes. Nullable.")
    tasks_accomplished: Mapped[str | None] = mapped_column(
        Text, comment="Free-text description of tasks done (see parked task_type option).")
    comment: Mapped[str | None] = mapped_column(Text, comment="Free-text notes.")

    party: Mapped["Party"] = relationship(back_populates="work_entries")  # noqa: F821
    orders: Mapped[list["CustomerOrder"]] = relationship(  # noqa: F821
        secondary=work_order, back_populates="work_sessions")

    __table_args__ = (
        CheckConstraint(
            "break_minutes IS NULL OR break_minutes >= 0", name="break_minutes_non_negative"),
        CheckConstraint(
            "start_at IS NULL OR end_at IS NULL OR end_at >= start_at", name="end_after_start"),
    )

    @property
    def order_ids(self) -> list[int]:
        """Flat list of linked order ids, for serialization."""
        return [o.customer_order_id for o in self.orders]
