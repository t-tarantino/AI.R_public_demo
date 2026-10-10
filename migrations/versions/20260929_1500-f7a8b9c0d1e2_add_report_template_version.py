"""add monthly_report.template_version

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-29 15:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monthly_report", sa.Column(
        "template_version", sa.Integer(), nullable=False, server_default="1",
        comment="Renderer version this PDF was built with; a final report is "
                "regenerated when the current template version is newer."))


def downgrade() -> None:
    op.drop_column("monthly_report", "template_version")
