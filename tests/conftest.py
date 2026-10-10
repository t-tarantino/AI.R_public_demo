"""Shared pytest fixtures.

Tests run against a throwaway in-memory SQLite database so they never touch the
developer's local `air.db`. The schema is created from the ORM metadata (the
same metadata the migrations are generated from).
"""
from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User
from app.services.security import hash_password


def _memory_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = _memory_engine()
    TestingSession = sessionmaker(bind=engine, future=True)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client():
    """Logged-in TestClient over a fresh in-memory DB (StaticPool shared)."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    engine = _memory_engine()
    TestingSession = sessionmaker(bind=engine, future=True)
    with TestingSession() as db:
        db.add(User(username="test", password_hash=hash_password("secret"), is_admin=True))
        db.commit()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            c.post("/api/auth/login", json={"username": "test", "password": "secret"})
            yield c
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
