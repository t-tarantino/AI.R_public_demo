"""add user_account.can_edit (read-only accounts)

A False value makes an account read-only: it can view everything but the server
rejects any create/update/delete. Existing accounts default to True (editors).

Revision ID: b8c9d0e1f2a3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-29 16:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain ADD COLUMN with a server default works on both SQLite and Postgres,
    # so no table rebuild / batch is needed.
    op.add_column("user_account", sa.Column(
        "can_edit", sa.Boolean(), nullable=False, server_default=sa.true(),
        comment="False = read-only account: can view but not create/modify anything."))


def downgrade() -> None:
    op.drop_column("user_account", "can_edit")