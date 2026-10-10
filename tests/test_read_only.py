"""A read-only account (can_edit=False) may view data but never change it."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User
from app.db.session import get_db
from app.main import app
from app.services.security import hash_password


def _client(can_edit: bool) -> TestClient:
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
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        db.add(User(username="u", password_hash=hash_password("secret"),
                    is_admin=False, can_edit=can_edit))
        db.commit()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "u", "password": "secret"})
    return c


def test_read_only_user_can_read_but_not_write():
    c = _client(can_edit=False)
    try:
        # Reads are allowed.
        assert c.get("/api/expense").status_code == 200
        # Writes are rejected with 403 before touching the database.
        resp = c.post("/api/expense", json={})
        assert resp.status_code == 403
        assert "sola lettura" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_read_only_user_cannot_use_richie_import():
    """Import is input-only: both preview and commit are POSTs, so the global
    guard must reject a read-only account on every import endpoint."""
    c = _client(can_edit=False)
    try:
        # The prompt (GET) is harmless and stays readable.
        assert c.get("/api/import/prompt/orders").status_code == 200
        # Every write path (preview + commit, all kinds) is blocked with 403.
        for kind in ("orders", "expenses", "stock", "work", "transfers"):
            for action in ("preview", "commit"):
                resp = c.post(f"/api/import/{kind}/{action}", json={})
                assert resp.status_code == 403, f"{kind}/{action} -> {resp.status_code}"
                assert "sola lettura" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_editor_user_is_not_blocked_by_the_guard():
    c = _client(can_edit=True)
    try:
        # An editor posting an invalid body gets a validation error (422),
        # NOT a read-only 403 — proving the guard lets editors through.
        resp = c.post("/api/expense", json={})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()