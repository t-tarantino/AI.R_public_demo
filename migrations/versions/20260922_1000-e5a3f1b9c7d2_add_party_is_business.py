"""add party.is_business and include it in the role check

Adds a role for our own company (AI.R) so the business can be a party
(payer/payee on expenses), distinct from the partner-workers.

SQLite doesn't reflect the named CHECK, so we rebuild the table via batch with an
explicit `copy_from` (existing columns, no old check); the physical rebuild drops
the old check and we add the new one that also accepts is_business.

Revision ID: e5a3f1b9c7d2
Revises: d7f2a1c9e4b8
Create Date: 2026-09-22 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.base import NAMING_CONVENTION

# revision identifiers, used by Alembic.
revision: str = 'e5a3f1b9c7d2'
down_revision: Union[str, None] = 'd7f2a1c9e4b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_party() -> sa.Table:
    """Existing `party` structure WITHOUT the role check (so the rebuild drops it)."""
    return sa.Table(
        "party", sa.MetaData(naming_convention=NAMING_CONVENTION),
        sa.Column("party_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code_nickname", sa.String(50)),
        sa.Column("is_customer", sa.Boolean(), nullable=False),
        sa.Column("is_supplier", sa.Boolean(), nullable=False),
        sa.Column("is_worker", sa.Boolean(), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("phone", sa.String(50)),
        sa.Column("email", sa.String(200)),
        sa.Column("website", sa.String(300)),
        sa.Column("comment", sa.Text()),
        sa.UniqueConstraint("code_nickname", name="code_nickname"),
    )


def upgrade() -> None:
    is_business = sa.Column("is_business", sa.Boolean(), nullable=False,
                            server_default=sa.false(),
                            comment="True for our own company (AI.R).")
    role_check = "is_customer OR is_supplier OR is_worker OR is_business"
    if op.get_bind().dialect.name == "sqlite":
        # SQLite can't ALTER a CHECK: rebuild the table (drops the old check).
        with op.batch_alter_table("party", copy_from=_existing_party(),
                                  recreate="always",
                                  naming_convention=NAMING_CONVENTION) as b:
            b.add_column(is_business)
            b.create_check_constraint("at_least_one_role", role_check)
    else:
        # Postgres: native ALTER — swap the CHECK in place, no table rebuild
        # (rebuilding would fail on the FKs that reference party.party_id).
        op.add_column("party", is_business)
        op.drop_constraint(op.f("ck_party_at_least_one_role"), "party", type_="check")
        op.create_check_constraint(op.f("ck_party_at_least_one_role"), "party", role_check)


def downgrade() -> None:
    role_check = "is_customer OR is_supplier OR is_worker"
    if op.get_bind().dialect.name == "sqlite":
        existing = _existing_party()
        existing.append_column(sa.Column("is_business", sa.Boolean(), nullable=False))
        with op.batch_alter_table("party", copy_from=existing, recreate="always",
                                  naming_convention=NAMING_CONVENTION) as b:
            b.drop_column("is_business")
            b.create_check_constraint("at_least_one_role", role_check)
    else:
        op.drop_constraint(op.f("ck_party_at_least_one_role"), "party", type_="check")
        op.drop_column("party", "is_business")
        op.create_check_constraint(op.f("ck_party_at_least_one_role"), "party", role_check)
