"""add party.credit_hours

Manual 'credit' hours per worker, counted ONLY in the Time-page ranking board
(never in money, profit, work totals or any other calculation). A plain nullable
numeric column with a 0 default: no CHECK/constraint change, so a straight
add_column/drop_column works on both SQLite and Postgres (no table rebuild).

Revision ID: d2e3f4a5b6c7
Revises: b0c1d2e3f4a5
Create Date: 2026-10-02 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'b0c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "party",
        sa.Column(
            "credit_hours", sa.Numeric(6, 2), nullable=False, server_default="0",
            comment="Manual 'credit' hours for a worker, counted ONLY in the Time-page "
                    "ranking board (never in money, profit, work totals or any other "
                    "calculation). Lets a worker's ranking position be nudged for "
                    "off-the-books contributions.",
        ),
    )


def downgrade() -> None:
    op.drop_column("party", "credit_hours")