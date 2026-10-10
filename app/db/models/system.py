"""System tables for the web app: users and audit log.

These are NOT business-domain tables. `user_account` holds login credentials for
the private web app; `audit_log` records who did what (a lightweight stand-in
for the full write-model described in the roadmap docs).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """A login account for the private web app (username + password, no email)."""

    __tablename__ = "user_account"

    user_id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, comment="Login name, unique, case-sensitive.")
    password_hash: Mapped[str] = mapped_column(
        String(200), comment="bcrypt hash of the password. Never the plain password.")
    party_id: Mapped[int | None] = mapped_column(
        ForeignKey("party.party_id"),
        comment="Optional link to the worker party this account belongs to.")
    is_admin: Mapped[bool] = mapped_column(
        default=False, comment="Admins can manage users.")
    can_edit: Mapped[bool] = mapped_column(
        default=True, server_default=true(),
        comment="False = read-only account: can view but not create/modify anything.")
    active: Mapped[bool] = mapped_column(
        default=True, comment="False blocks login without deleting the account.")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, comment="Account creation time (UTC).")

    party: Mapped["Party | None"] = relationship()  # noqa: F821
    audit_entries: Mapped[list["AuditLog"]] = relationship(back_populates="user")


class AuditLog(Base):
    """One row per successful mutation done through the web app: who did what."""

    __tablename__ = "audit_log"

    audit_log_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.user_id"), comment="The account that performed the action.")
    action: Mapped[str] = mapped_column(
        String(20), comment="create | update | deactivate | delete | login.")
    entity: Mapped[str] = mapped_column(
        String(50), comment="Entity/table name affected, e.g. 'composition'.")
    entity_id: Mapped[int | None] = mapped_column(
        comment="Primary key of the affected record. NULL for non-record actions (login).")
    changes: Mapped[str | None] = mapped_column(
        Text, comment="Short JSON of the changed fields (before/after), optional.")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, comment="When the action happened (UTC).")

    user: Mapped["User"] = relationship(back_populates="audit_entries")

    __table_args__ = (
        CheckConstraint(
            "action IN ('create','update','deactivate','delete','login')",
            name="action_valid"),
    )