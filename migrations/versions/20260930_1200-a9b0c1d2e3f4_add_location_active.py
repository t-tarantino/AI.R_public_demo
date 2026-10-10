"""add location.active (retire venues from new orders, keep history)

Revision ID: a9b0c1d2e3f4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-30 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("location", sa.Column(
        "active", sa.Boolean(), nullable=False, server_default=sa.true(),
        comment="False retires the venue from new orders, keeping its history."))


def downgrade() -> None:
    op.drop_column("location", "active")
