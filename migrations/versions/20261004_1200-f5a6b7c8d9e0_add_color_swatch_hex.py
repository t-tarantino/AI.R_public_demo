"""add color.swatch_hex

An optional per-colour display hex ('#rrggbb') so the swatch shown in Stock and
Products can be chosen from the app. NULL falls back to the built-in palette hex
(by code) or grey. Additive, nullable: a straight add_column/drop_column works on
SQLite and PostgreSQL.

Revision ID: f5a6b7c8d9e0
Revises: a5b6c7d8e9f0
Create Date: 2026-10-04 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "color",
        sa.Column(
            "swatch_hex", sa.String(length=7), nullable=True,
            comment="Optional display colour for the swatch in Stock/Products, as '#rrggbb'. "
                    "When NULL the UI falls back to the built-in palette hex (by code) or grey.",
        ),
    )


def downgrade() -> None:
    op.drop_column("color", "swatch_hex")
