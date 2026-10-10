"""add product.variant and product.is_first_choice

Two columns on `product` to support the Stock-page "+" reorder button:
  * variant        = the stock-cell variant this SKU refills (e.g. foil-number
                     digit '1'/'8'); NULL for the common case. With
                     (required_item_id, color_id) it pins the exact stock cell.
  * is_first_choice = marks the preferred SKU to reorder for that cell; the
                     Stock '+' button opens its link. At most one per cell is
                     enforced in the API, not by a DB constraint.

Both are additive, nullable-safe (variant nullable, is_first_choice has a false
server_default), so a plain add_column/drop_column works on SQLite and Postgres.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-10-03 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column(
            "variant", sa.String(length=20), nullable=True,
            comment="Variant this SKU is for, e.g. the digit '1'/'8' of a foil number. "
                    "NULL for materials without a per-variant SKU (most products). Together "
                    "with (required_item_id, color_id) it identifies the exact stock cell "
                    "this product refills.",
        ),
    )
    op.add_column(
        "product",
        sa.Column(
            "is_first_choice", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="True = the preferred product to (re)order for its exact stock cell "
                    "(required_item_id + color_id + variant). The Stock page '+' buy button "
                    "opens this product's link. At most one per cell (enforced in the API).",
        ),
    )


def downgrade() -> None:
    op.drop_column("product", "is_first_choice")
    op.drop_column("product", "variant")
