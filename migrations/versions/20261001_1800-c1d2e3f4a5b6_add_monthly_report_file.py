"""add monthly_report_file (PDFs stored in the database)

Report PDFs used to live on the server disk, which is wiped on every deploy and
restart. They are now stored in this new, separate table. No existing table is
modified.

Revision ID: c1d2e3f4a5b6
Revises: a9b0c1d2e3f4
Create Date: 2026-10-01 18:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monthly_report_file",
        sa.Column("monthly_report_id", sa.Integer(), nullable=False,
                  comment="The report this PDF belongs to (one-to-one)."),
        sa.Column("pdf_data", sa.LargeBinary(), nullable=False, comment="The PDF file content."),
        sa.ForeignKeyConstraint(["monthly_report_id"], ["monthly_report.monthly_report_id"],
                                name=op.f("fk_monthly_report_file_monthly_report_id_monthly_report"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("monthly_report_id", name=op.f("pk_monthly_report_file")),
    )


def downgrade() -> None:
    op.drop_table("monthly_report_file")
