"""add color.in_catalog and order_item_color.color_surcharge

Modella i colori fuori catalogo e il sovrapprezzo storico ad essi legato:
- color.in_catalog  (bool)  : False = colore speciale/fuori catalogo.
- order_item_color.color_surcharge (money) : sovrapprezzo storico di quella riga.

Revision ID: c4e1a9b7d2f3
Revises: aac27f2bf79b
Create Date: 2026-09-21 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.base import NAMING_CONVENTION

# revision identifiers, used by Alembic.
revision: str = 'c4e1a9b7d2f3'
down_revision: Union[str, None] = 'aac27f2bf79b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('color', naming_convention=NAMING_CONVENTION) as b:
        b.add_column(sa.Column(
            'in_catalog', sa.Boolean(), nullable=False, server_default=sa.true(),
            comment="True = standard palette color. False = special/off-catalog "
                    "color: its use adds a surcharge."))

    with op.batch_alter_table('order_item_color', naming_convention=NAMING_CONVENTION) as b:
        b.add_column(sa.Column(
            'color_surcharge', sa.Numeric(precision=10, scale=2), nullable=False,
            server_default='0',
            comment="HISTORICAL surcharge (EUR) charged for using this color on this "
                    "line (0 if none). Snapshot; never recomputed."))
        b.create_check_constraint('color_surcharge_non_negative', 'color_surcharge >= 0')


def downgrade() -> None:
    with op.batch_alter_table('order_item_color', naming_convention=NAMING_CONVENTION) as b:
        b.drop_constraint(op.f('ck_order_item_color_color_surcharge_non_negative'),
                          type_='check')
        b.drop_column('color_surcharge')
    with op.batch_alter_table('color', naming_convention=NAMING_CONVENTION) as b:
        b.drop_column('in_catalog')
