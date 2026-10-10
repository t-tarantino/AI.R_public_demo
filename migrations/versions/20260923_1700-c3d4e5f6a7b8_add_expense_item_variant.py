"""add expense_item.variant (digit for number-balloon purchases)

Number purchases carry a digit (0-9) so the refill can raise stock at the right
(size, colour, digit). NULL for every non-number line.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-23 17:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("expense_item", sa.Column(
        "variant", sa.String(length=20), nullable=True,
        comment="Digit ('0'..'9') for number-balloon purchases; NULL otherwise."))


def downgrade() -> None:
    with op.batch_alter_table("expense_item") as b:
        b.drop_column("variant")