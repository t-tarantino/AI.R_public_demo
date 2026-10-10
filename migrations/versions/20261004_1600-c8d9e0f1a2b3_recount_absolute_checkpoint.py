"""recounts become absolute checkpoints (not deltas)

Stock is derived as: the LATEST recount per (material, colour, digit) fixes the
quantity at its date, and only movements strictly after it count. For that a
recount row must store the counted ABSOLUTE in quantity_change, not a delta.

This migration:
  1. drops the `quantity_change <> 0` CHECK (an empty recount stores 0);
  2. converts every EXISTING recount row from its stored delta to the absolute it
     represented — the running sum of the cell up to and including that row (which,
     by the old delta convention, equals the counted value at that moment).

No-op on a database with no recount rows (e.g. a fresh test DB).

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-10-04 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORDERED = sa.text(
    "SELECT i.inventory_update_item_id AS iid, i.required_item_id AS rid, "
    "i.color_id AS cid, i.variant AS variant, i.quantity_change AS qc, u.type AS type "
    "FROM inventory_update_item i "
    "JOIN inventory_update u ON u.inventory_update_id = i.inventory_update_id "
    "ORDER BY i.required_item_id, i.color_id, i.variant, u.date, "
    "u.inventory_update_id, i.inventory_update_item_id")

_SET = sa.text("UPDATE inventory_update_item SET quantity_change = :v "
               "WHERE inventory_update_item_id = :id")


def upgrade() -> None:
    with op.batch_alter_table("inventory_update_item") as batch_op:
        batch_op.drop_constraint("quantity_change_non_zero", type_="check")

    conn = op.get_bind()
    running: dict[tuple, int] = {}
    to_set: list[tuple[int, int]] = []
    for r in conn.execute(_ORDERED).mappings():
        cell = (r["rid"], r["cid"], r["variant"])
        running[cell] = running.get(cell, 0) + int(r["qc"])   # cumulative (old delta space)
        if r["type"] == "recount":
            to_set.append((r["iid"], running[cell]))           # absolute = counted value then
    for iid, absval in to_set:
        conn.execute(_SET, {"v": absval, "id": iid})


def downgrade() -> None:
    conn = op.get_bind()
    running: dict[tuple, int] = {}
    to_set: list[tuple[int, int]] = []
    for r in conn.execute(_ORDERED).mappings():
        cell = (r["rid"], r["cid"], r["variant"])
        if r["type"] == "recount":
            delta = int(r["qc"]) - running.get(cell, 0)        # qc is absolute now
            to_set.append((r["iid"], delta))
            running[cell] = running.get(cell, 0) + delta
        else:
            running[cell] = running.get(cell, 0) + int(r["qc"])
    for iid, delta in to_set:
        conn.execute(_SET, {"v": delta, "id": iid})

    with op.batch_alter_table("inventory_update_item") as batch_op:
        batch_op.create_check_constraint("quantity_change_non_zero", "quantity_change <> 0")
