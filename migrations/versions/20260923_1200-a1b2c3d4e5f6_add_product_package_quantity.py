"""add product.package_quantity (pack size for stock refill)

Expenses record purchased units (packs); stock is counted in pieces. Each SKU
stores how many pieces a purchased unit contains, so the refill can multiply.

SQLite can't add a CHECK via plain ALTER, so we rebuild the table via batch with
an explicit `copy_from` (existing columns), then add the column and its check.

Revision ID: a1b2c3d4e5f6
Revises: 4eba21603dc2
Create Date: 2026-09-23 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.base import NAMING_CONVENTION

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '4eba21603dc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_product() -> sa.Table:
    """Existing `product` structure (before package_quantity)."""
    return sa.Table(
        "product", sa.MetaData(naming_convention=NAMING_CONVENTION),
        sa.Column("product_id", sa.Integer(), primary_key=True),
        sa.Column("required_item_id", sa.Integer(), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=True),
        sa.Column("product_code", sa.String(100)),
        sa.Column("product_link", sa.String(500)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.ForeignKeyConstraint(["color_id"], ["color.color_id"],
                                name=op.f("fk_product_color_id_color")),
        sa.ForeignKeyConstraint(["required_item_id"], ["required_item.required_item_id"],
                                name=op.f("fk_product_required_item_id_required_item")),
    )


def upgrade() -> None:
    package_quantity = sa.Column(
        "package_quantity", sa.Integer(), nullable=False, server_default="1",
        comment="Pieces per purchased unit (pack size); refill multiplies by this.")
    if op.get_bind().dialect.name == "sqlite":
        # SQLite can't add a CHECK via plain ALTER: rebuild the table.
        with op.batch_alter_table("product", copy_from=_existing_product(),
                                  recreate="always",
                                  naming_convention=NAMING_CONVENTION) as b:
            b.add_column(package_quantity)
            b.create_check_constraint("package_quantity_positive", "package_quantity > 0")
    else:
        # Postgres: native ALTER, no rebuild (product is referenced by FKs).
        op.add_column("product", package_quantity)
        op.create_check_constraint(
            op.f("ck_product_package_quantity_positive"), "product", "package_quantity > 0")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        existing = _existing_product()
        existing.append_column(sa.Column("package_quantity", sa.Integer(), nullable=False))
        with op.batch_alter_table("product", copy_from=existing, recreate="always",
                                  naming_convention=NAMING_CONVENTION) as b:
            b.drop_column("package_quantity")
    else:
        op.drop_constraint(
            op.f("ck_product_package_quantity_positive"), "product", type_="check")
        op.drop_column("product", "package_quantity")