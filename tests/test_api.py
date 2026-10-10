"""API tests: auth, CRUD, BOM, audit — against an in-memory database."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User
from app.db.session import get_db
from app.main import app
from app.services.security import hash_password


@pytest.fixture()
def client():
    # StaticPool: one shared connection, so the in-memory DB is visible from
    # every thread TestClient uses.
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
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
            yield c
    finally:
        app.dependency_overrides.clear()


def _login(client):
    resp = client.post("/api/auth/login", json={"username": "test", "password": "secret"})
    assert resp.status_code == 200


def test_endpoints_require_login(client):
    assert client.get("/api/color").status_code == 401


def test_color_crud_and_audit(client):
    _login(client)
    created = client.post("/api/color", json={"code": "045", "name": "Rosso"})
    assert created.status_code == 201
    color_id = created.json()["color_id"]

    # Duplicate code -> readable 400
    assert client.post("/api/color", json={"code": "045", "name": "Doppione"}).status_code == 400

    updated = client.patch(f"/api/color/{color_id}", json={"name": "Rosso vivo"})
    assert updated.json()["name"] == "Rosso vivo"

    deactivated = client.patch(f"/api/color/{color_id}", json={"active": False})
    assert deactivated.json()["active"] is False

    activity = client.get("/api/activity").json()
    actions = [(a["action"], a["entity"]) for a in activity]
    assert ("create", "color") in actions
    assert ("update", "color") in actions
    assert ("deactivate", "color") in actions
    assert all(a["username"] == "test" for a in activity)


def test_party_requires_role(client):
    _login(client)
    resp = client.post("/api/party", json={"name": "Nessuno"})
    assert resp.status_code == 422  # pydantic model validator


def test_expense_category_delete_guard(client):
    _login(client)
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    sup = client.post("/api/party", json={"name": "Amazon", "is_supplier": True}).json()

    # An unused category deletes cleanly.
    unused = client.post("/api/expense_category", json={"name": "unused"}).json()
    assert client.delete(f"/api/expense_category/{unused['expense_category_id']}").status_code == 200

    # A category in use is refused, with a helpful message; it survives.
    used = client.post("/api/expense_category", json={"name": "materials"}).json()
    client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": sup["party_id"],
        "date": "2026-06-01",
        "items": [{"expense_category_id": used["expense_category_id"], "quantity": 1,
                   "unit_cost": "10.00", "description": "stuff"}]})
    resp = client.delete(f"/api/expense_category/{used['expense_category_id']}")
    assert resp.status_code == 400
    assert "still use it" in resp.json()["detail"]
    assert client.get(f"/api/expense_category/{used['expense_category_id']}").status_code == 200


def test_bom_replace(client):
    _login(client)
    comp = client.post("/api/composition", json={
        "code": "001", "name": "Arco", "standard_price": "85.00"}).json()
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()

    put = client.put(f"/api/composition/{comp['composition_id']}/bom",
                     json=[{"required_item_id": item["required_item_id"],
                            "quantity": "80"}])
    assert put.status_code == 200
    bom = client.get(f"/api/composition/{comp['composition_id']}/bom").json()
    assert len(bom) == 1
    assert Decimal(str(bom[0]["quantity"])) == Decimal("80")

    # Duplicate material in one BOM -> 400
    dup = client.put(f"/api/composition/{comp['composition_id']}/bom",
                     json=[{"required_item_id": item["required_item_id"], "quantity": "1"},
                           {"required_item_id": item["required_item_id"], "quantity": "2"}])
    assert dup.status_code == 400


def test_product_single_first_choice_per_cell(client):
    _login(client)
    grande = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()
    piccolo = client.post("/api/required_item", json={
        "name": "Palloncino piccolo", "unit": "piece", "used_color": True}).json()
    rosso = client.post("/api/color", json={"code": "045", "name": "Rosso"}).json()
    blu = client.post("/api/color", json={"code": "010", "name": "Blu"}).json()
    ri, ci = grande["required_item_id"], rosso["color_id"]

    def mk(name, color_id, first):
        return client.post("/api/product", json={
            "name": name, "required_item_id": ri, "color_id": color_id,
            "product_link": "https://x/" + name, "is_first_choice": first}).json()

    a = mk("A", ci, True)
    b = mk("B", ci, True)   # same cell -> must steal first-choice from A
    assert client.get(f"/api/product/{a['product_id']}").json()["is_first_choice"] is False
    assert client.get(f"/api/product/{b['product_id']}").json()["is_first_choice"] is True

    # Different colour = different cell -> both can be first-choice at once.
    c = mk("C", blu["color_id"], True)
    assert client.get(f"/api/product/{b['product_id']}").json()["is_first_choice"] is True
    assert client.get(f"/api/product/{c['product_id']}").json()["is_first_choice"] is True

    # Different material (piccolo) with same colour = different cell too.
    d = client.post("/api/product", json={
        "name": "D", "required_item_id": piccolo["required_item_id"], "color_id": ci,
        "is_first_choice": True}).json()
    assert client.get(f"/api/product/{b['product_id']}").json()["is_first_choice"] is True
    assert client.get(f"/api/product/{d['product_id']}").json()["is_first_choice"] is True

    # Toggling an existing product on via PATCH also clears the sibling.
    client.patch(f"/api/product/{a['product_id']}", json={"is_first_choice": True})
    assert client.get(f"/api/product/{a['product_id']}").json()["is_first_choice"] is True
    assert client.get(f"/api/product/{b['product_id']}").json()["is_first_choice"] is False


def test_product_sole_is_auto_first_choice(client):
    _login(client)
    ri = client.post("/api/required_item", json={
        "name": "Nastro", "unit": "mt"}).json()["required_item_id"]

    # First product of a cell is auto-flagged even without asking.
    a = client.post("/api/product", json={"name": "A", "required_item_id": ri}).json()
    assert a["is_first_choice"] is True

    # A second product in the same cell is NOT auto-flagged (ambiguous now),
    # and the sole one keeps its flag until the user changes it.
    b = client.post("/api/product", json={"name": "B", "required_item_id": ri}).json()
    assert b["is_first_choice"] is False
    assert client.get(f"/api/product/{a['product_id']}").json()["is_first_choice"] is True


def test_change_password(client):
    _login(client)
    bad = client.post("/api/auth/change_password",
                      json={"current_password": "wrong", "new_password": "nuova123"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/change_password",
                     json={"current_password": "secret", "new_password": "nuova123"})
    assert ok.status_code == 200
    relog = client.post("/api/auth/login", json={"username": "test", "password": "nuova123"})
    assert relog.status_code == 200