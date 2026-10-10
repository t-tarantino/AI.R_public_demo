"""Health and database-connectivity endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness check — does not touch the database."""
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    """Readiness check — verifies the database answers a trivial query."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
