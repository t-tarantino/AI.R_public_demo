"""inventory movement types: recount / loss / gift (manual), migrate correction/damage

Manual stock updates are now recount (absolute), loss (-) and gift (+). Existing
'correction' rows become 'recount' and 'damage' rows become 'loss'. purchase and
order_usage (auto) are unchanged.

Revision ID: b0c1d2e3f4a5
Revises: c1d2e3f4a5b6
Create Date: 2026-10-01 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.base import NAMING_CONVENTION

revision: str = 'b0c1d2e3f4a5'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_CHECK = "type IN ('purchase', 'order_usage', 'recount', 'loss', 'gift')"
OLD_CHECK = "type IN ('purchase', 'order_usage', 'damage', 'correction')"


def _existing() -> sa.Table:
    """`inventory_update` columns WITHOUT the old check (so the rebuild drops it)."""
    return sa.Table(
        "inventory_update", sa.MetaData(naming_convention=NAMING_CONVENTION),
        sa.Column("inventory_update_id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text()),
    )


def upgrade() -> None:
    cname = op.f("ck_inventory_update_movement_type_valid")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("UPDATE inventory_update SET type='recount' WHERE type='correction'")
        op.execute("UPDATE inventory_update SET type='loss' WHERE type='damage'")
        with op.batch_alter_table("inventory_update", copy_from=_existing(),
                                  recreate="always", naming_convention=NAMING_CONVENTION) as b:
            b.create_check_constraint("movement_type_valid", NEW_CHECK)
    else:
        op.drop_constraint(cname, "inventory_update", type_="check")
        op.execute("UPDATE inventory_update SET type='recount' WHERE type='correction'")
        op.execute("UPDATE inventory_update SET type='loss' WHERE type='damage'")
        op.create_check_constraint(cname, "inventory_update", NEW_CHECK)


def downgrade() -> None:
    cname = op.f("ck_inventory_update_movement_type_valid")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("UPDATE inventory_update SET type='correction' WHERE type IN ('recount','gift')")
        op.execute("UPDATE inventory_update SET type='damage' WHERE type='loss'")
        with op.batch_alter_table("inventory_update", copy_from=_existing(),
                                  recreate="always", naming_convention=NAMING_CONVENTION) as b:
            b.create_check_constraint("movement_type_valid", OLD_CHECK)
    else:
        op.drop_constraint(cname, "inventory_update", type_="check")
        op.execute("UPDATE inventory_update SET type='correction' WHERE type IN ('recount','gift')")
        op.execute("UPDATE inventory_update SET type='damage' WHERE type='loss'")
        op.create_check_constraint(cname, "inventory_update", OLD_CHECK)
