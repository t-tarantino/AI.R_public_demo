"""work<->customer_order many-to-many (a session covers several orders)

Replaces the single `work.customer_order_id` FK with an association table
`work_order`, because a work shift normally covers all the compositions/orders
built that day (1:1 is just the single-order day).

Revision ID: d7f2a1c9e4b8
Revises: c4e1a9b7d2f3
Create Date: 2026-09-21 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.base import NAMING_CONVENTION

# revision identifiers, used by Alembic.
revision: str = 'd7f2a1c9e4b8'
down_revision: Union[str, None] = 'c4e1a9b7d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'work_order',
        sa.Column('work_id', sa.Integer(), nullable=False),
        sa.Column('customer_order_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['work_id'], ['work.work_id'],
                                name=op.f('fk_work_order_work_id_work')),
        sa.ForeignKeyConstraint(['customer_order_id'], ['customer_order.customer_order_id'],
                                name=op.f('fk_work_order_customer_order_id_customer_order')),
        sa.PrimaryKeyConstraint('work_id', 'customer_order_id', name=op.f('pk_work_order')),
    )
    with op.batch_alter_table('work', naming_convention=NAMING_CONVENTION) as b:
        b.drop_column('customer_order_id')


def downgrade() -> None:
    with op.batch_alter_table('work', naming_convention=NAMING_CONVENTION) as b:
        b.add_column(sa.Column('customer_order_id', sa.Integer(), nullable=True))
        b.create_foreign_key(op.f('fk_work_customer_order_id_customer_order'),
                             'customer_order', ['customer_order_id'], ['customer_order_id'])
    op.drop_table('work_order')
