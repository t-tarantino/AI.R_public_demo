"""add money_transfer table

Generic cash-movement ledger between two parties (any two, not necessarily
involving the business): settles debts created by expenses (fronted costs)
or orders (customer revenue) without being either itself.

Revision ID: 4eba21603dc2
Revises: e5a3f1b9c7d2
Create Date: 2026-09-22 17:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4eba21603dc2'
down_revision: Union[str, None] = 'e5a3f1b9c7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "money_transfer",
        sa.Column("money_transfer_id", sa.Integer(), primary_key=True),
        sa.Column("from_party_id", sa.Integer(),
                  sa.ForeignKey("party.party_id"), nullable=False,
                  comment="Party that gave the money."),
        sa.Column("to_party_id", sa.Integer(),
                  sa.ForeignKey("party.party_id"), nullable=False,
                  comment="Party that received the money."),
        sa.Column("date", sa.Date(), nullable=False,
                  comment="Date the transfer happened."),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False,
                  comment="Amount moved (> 0)."),
        sa.Column("payment_method", sa.String(50),
                  comment="e.g. 'card', 'cash', 'transfer'. Nullable."),
        sa.Column("comment", sa.Text(),
                  comment="Free-text notes, e.g. what debt this settles."),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.CheckConstraint("from_party_id <> to_party_id", name="from_differs_from_to"),
    )


def downgrade() -> None:
    op.drop_table("money_transfer")
