"""add product.default_price

An optional usual cost per purchased unit (pack), same unit as
expense_item.unit_cost. Nullable: only a convenience default that pre-fills
expense entry and flags a diff when the entered cost differs. It never overrides
the frozen historical unit_cost and is not auto-updated from purchases.

Additive and nullable; batch_alter_table keeps the CHECK portable on SQLite.

Revision ID: b7c8d9e0f1a2
Revises: f5a6b7c8d9e0
Create Date: 2026-10-04 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("product") as batch_op:
        batch_op.add_column(
            sa.Column(
                "default_price", sa.Numeric(10, 2), nullable=True,
                comment="Usual cost per purchased unit (pack), same unit as "
                        "expense_item.unit_cost. Convenience default + sanity-check only.",
            )
        )
        batch_op.create_check_constraint(
            "default_price_non_negative", "default_price IS NULL OR default_price >= 0")


def downgrade() -> None:
    with op.batch_alter_table("product") as batch_op:
        batch_op.drop_constraint("default_price_non_negative", type_="check")
        batch_op.drop_column("default_price")
