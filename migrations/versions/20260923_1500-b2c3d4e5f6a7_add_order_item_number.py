"""add order_item_number + required_item.is_number

Foil number balloons have a per-order digit/colour/size, independent of the
item's balloon colour mix. `required_item.is_number` flags the number materials
so consumption skips the BOM colour split for them and reads the new
`order_item_number` detail instead.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-23 15:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("required_item", sa.Column(
        "is_number", sa.Boolean(), nullable=False, server_default="0",
        comment="True for foil number balloons (0-9); digit/colour/size chosen per order."))
    # Flag the existing number materials.
    op.execute("UPDATE required_item SET is_number = true WHERE name LIKE 'Palloncino numero%'")

    op.create_table(
        "order_item_number",
        sa.Column("order_item_number_id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=False,
                  comment="The sold line this number belongs to."),
        sa.Column("required_item_id", sa.Integer(), nullable=False,
                  comment="The number material/size used."),
        sa.Column("color_id", sa.Integer(), nullable=False,
                  comment="Number colour (independent; default gold)."),
        sa.Column("digit", sa.String(length=1), nullable=False, comment="The digit shown, '0'..'9'."),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1",
                  comment="How many of this digit/colour/size (> 0)."),
        sa.Column("comment", sa.Text(), nullable=True, comment="Free-text notes."),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_item_number_oin_quantity_positive")),
        sa.CheckConstraint("digit >= '0' AND digit <= '9'",
                           name=op.f("ck_order_item_number_oin_digit_valid")),
        sa.ForeignKeyConstraint(["color_id"], ["color.color_id"],
                                name=op.f("fk_order_item_number_color_id_color")),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_item.order_item_id"],
                                name=op.f("fk_order_item_number_order_item_id_order_item")),
        sa.ForeignKeyConstraint(["required_item_id"], ["required_item.required_item_id"],
                                name=op.f("fk_order_item_number_required_item_id_required_item")),
        sa.PrimaryKeyConstraint("order_item_number_id", name=op.f("pk_order_item_number")),
    )


def downgrade() -> None:
    op.drop_table("order_item_number")
    with op.batch_alter_table("required_item") as b:
        b.drop_column("is_number")