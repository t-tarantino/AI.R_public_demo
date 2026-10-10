"""backfill first_choice for sole products

Data migration (no schema change): every stock cell (required_item_id + color_id
+ variant) that has exactly one product and no first-choice yet gets that lone
product flagged. This mirrors the create-time rule in the API, so existing data
behaves like newly entered data: the single product of a cell is the one the
Stock '+' button opens.

Grouping is done in Python so NULL colour/variant are compared correctly on both
SQLite (local) and PostgreSQL (prod) without dialect-specific NULL-safe operators.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-10-03 14:00:00.000000
"""
from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT product_id, required_item_id, color_id, variant, is_first_choice "
        "FROM product"
    )).fetchall()

    cells: dict[tuple, list] = defaultdict(list)
    for r in rows:
        cells[(r.required_item_id, r.color_id, r.variant)].append(r)

    sole_without_fc = [
        prods[0].product_id
        for prods in cells.values()
        if len(prods) == 1 and not prods[0].is_first_choice
    ]
    for pid in sole_without_fc:
        # Bind a Python bool so each driver adapts it to its own boolean literal
        # (TRUE on PostgreSQL, 1 on SQLite). A bare `= 1` fails on PostgreSQL,
        # whose boolean column rejects an integer expression.
        bind.execute(
            sa.text("UPDATE product SET is_first_choice = :val WHERE product_id = :id"),
            {"val": True, "id": pid},
        )


def downgrade() -> None:
    # One-way data fix: we can't tell auto-set flags from manually-set ones, so
    # downgrade is a no-op (leaving the flags in place is harmless).
    pass
