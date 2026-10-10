"""Audit helper: one row in audit_log per successful mutation."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog, User

# Keep audit payloads small: long text fields are truncated.
_MAX_VALUE_LEN = 200


def _compact(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_VALUE_LEN:
        return value[:_MAX_VALUE_LEN] + "…"
    return value


def log_action(
    db: Session,
    user: User,
    action: str,
    entity: str,
    entity_id: int | None,
    changes: dict[str, Any] | None = None,
) -> None:
    """Append an audit row. Call inside the same transaction as the mutation."""
    payload = None
    if changes:
        payload = json.dumps(
            {k: _compact(v) for k, v in changes.items()},
            ensure_ascii=False, default=str)
    db.add(AuditLog(user_id=user.user_id, action=action, entity=entity,
                    entity_id=entity_id, changes=payload))