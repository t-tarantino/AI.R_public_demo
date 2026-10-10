"""add party.hidden_from_ranking

A per-worker flag to hide them from the Time-page ranking board (and its credit
footer). Plain nullable-free boolean with a false default: no CHECK/constraint
change, so a straight add_column/drop_column works on SQLite and Postgres.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-03 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "party",
        sa.Column(
            "hidden_from_ranking", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="True hides this worker from the Time-page ranking board (and its "
                    "credit-hours footer). Does not affect work sessions or any other "
                    "calculation.",
        ),
    )


def downgrade() -> None:
    op.drop_column("party", "hidden_from_ranking")
