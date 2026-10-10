"""Monthly report snapshots.

One row per calendar month: a frozen, complete money-flow report (revenue,
expenses, transfers) rendered to a PDF file on disk. Past (closed) months are
`final` and generated once; the current month can be produced on demand as
`provisional`. Totals are stored alongside for quick listing without reopening
the PDF. The numbers are historical facts (never recomputed), so a `final`
snapshot is stable, but it can still be regenerated if past data is corrected.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, LargeBinary, Numeric, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MONEY = Numeric(10, 2)


class MonthlyReport(Base):
    """A stored monthly money-flow report (metadata + path to its PDF)."""

    __tablename__ = "monthly_report"

    monthly_report_id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(comment="Calendar year, e.g. 2026.")
    month: Mapped[int] = mapped_column(comment="Calendar month, 1..12.")
    status: Mapped[str] = mapped_column(
        String(20), default="final",
        comment="'final' (month closed) | 'provisional' (current, still open).")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
        comment="When this snapshot was last generated.")
    template_version: Mapped[int] = mapped_column(
        default=1, server_default="1",
        comment="Renderer version this PDF was built with; a final report is "
                "regenerated when the current template version is newer.")
    revenue_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    expense_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    transfer_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    profit_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    order_count: Mapped[int] = mapped_column(default=0)
    expense_count: Mapped[int] = mapped_column(default=0)
    transfer_count: Mapped[int] = mapped_column(default=0)
    file_path: Mapped[str] = mapped_column(
        String(300), comment="Path to the rendered PDF, relative to the project root.")

    __table_args__ = (
        UniqueConstraint("year", "month", name="monthly_report_year_month_unique"),
        CheckConstraint("month >= 1 AND month <= 12", name="month_valid"),
        CheckConstraint("status IN ('final', 'provisional')", name="status_valid"),
    )


class MonthlyReportFile(Base):
    """The stored PDF of a monthly report.

    Kept in the database (not on disk) because the hosting disk is ephemeral.
    Written only when a report is generated; reads never regenerate it.
    """

    __tablename__ = "monthly_report_file"

    monthly_report_id: Mapped[int] = mapped_column(
        ForeignKey("monthly_report.monthly_report_id", ondelete="CASCADE"),
        primary_key=True, comment="The report this PDF belongs to (one-to-one).")
    pdf_data: Mapped[bytes] = mapped_column(LargeBinary, comment="The PDF file content.")
