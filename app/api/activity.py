"""Activity-log read endpoint: a register of *data changes* (who changed what).

Only data mutations are surfaced here — login/logout and account events are
deliberately excluded (they are not changes to business data). Entities are
split into two categories:

  * "operations" — the primary transactional datasets: orders, expenses, work
    hours, money transfers and stock movements (manual + auto consumption/refill).
  * "master"     — reference/master data: price list, products, compositions/BOM,
    parties, colors, thresholds, etc.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, joinedload

from app.api.auth import get_current_user
from app.db.models import AuditLog, User
from app.db.session import get_db

router = APIRouter(prefix="/api/activity", tags=["activity"])

# The transactional datasets (day-to-day operations).
OPERATIONS_ENTITIES = {
    "customer_order",
    "expense",
    "work",
    "money_transfer",
    "inventory_update",
}
# Reference / master data.
MASTER_ENTITIES = {
    "party",
    "location",
    "color",
    "composition",
    "composition_bom",
    "expense_category",
    "required_item",
    "product",
    "stock_threshold",
}
# Everything the register should show, mapped to its category.
ENTITY_CATEGORY: dict[str, str] = (
    {e: "operations" for e in OPERATIONS_ENTITIES}
    | {e: "master" for e in MASTER_ENTITIES}
)


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_log_id: int
    username: str
    action: str
    entity: str
    category: str
    entity_id: int | None
    changes: str | None
    timestamp: datetime


@router.get("", response_model=list[ActivityRead])
def list_activity(
    category: str | None = Query(default=None, pattern="^(operations|master)$"),
    entity: str | None = Query(default=None),
    username: str | None = Query(default=None),
    limit: int = Query(default=150, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List data-change events, newest first.

    Filters: `category` (operations|master), `entity`, `username`. Login and
    account events are never returned — this is a data-change register only.
    """
    if category == "operations":
        wanted = OPERATIONS_ENTITIES
    elif category == "master":
        wanted = MASTER_ENTITIES
    else:
        wanted = set(ENTITY_CATEGORY)

    q = (db.query(AuditLog).options(joinedload(AuditLog.user))
         .filter(AuditLog.entity.in_(wanted))
         .order_by(AuditLog.timestamp.desc(), AuditLog.audit_log_id.desc()))
    if entity:
        q = q.filter(AuditLog.entity == entity)
    if username:
        q = q.join(AuditLog.user).filter(User.username == username)
    rows = q.limit(limit).all()
    return [ActivityRead(
        audit_log_id=r.audit_log_id, username=r.user.username, action=r.action,
        entity=r.entity, category=ENTITY_CATEGORY.get(r.entity, "operations"),
        entity_id=r.entity_id, changes=r.changes,
        timestamp=r.timestamp) for r in rows]
