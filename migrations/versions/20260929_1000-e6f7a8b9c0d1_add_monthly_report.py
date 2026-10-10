"""add monthly_report (frozen monthly money-flow snapshots)

Revision ID: e6f7a8b9c0d1
Revises: c3d4e5f6a7b8
Create Date: 2026-09-29 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monthly_report",
        sa.Column("monthly_report_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False, comment="Calendar year, e.g. 2026."),
        sa.Column("month", sa.Integer(), nullable=False, comment="Calendar month, 1..12."),
        sa.Column("status", sa.String(length=20), nullable=False,
                  comment="'final' (month closed) | 'provisional' (current, still open)."),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False,
                  comment="When this snapshot was last generated."),
        sa.Column("revenue_total", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("expense_total", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("transfer_total", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("profit_total", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("order_count", sa.Integer(), nullable=False),
        sa.Column("expense_count", sa.Integer(), nullable=False),
        sa.Column("transfer_count", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=300), nullable=False,
                  comment="Path to the rendered PDF, relative to the project root."),
        sa.CheckConstraint("month >= 1 AND month <= 12", name=op.f("ck_monthly_report_month_valid")),
        sa.CheckConstraint("status IN ('final', 'provisional')", name=op.f("ck_monthly_report_status_valid")),
        sa.PrimaryKeyConstraint("monthly_report_id", name=op.f("pk_monthly_report")),
        sa.UniqueConstraint("year", "month", name=op.f("uq_monthly_report_year_month_unique")),
    )


def downgrade() -> None:
    op.drop_table("monthly_report")
