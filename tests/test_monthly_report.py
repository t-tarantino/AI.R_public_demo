"""Monthly report snapshot tests."""
from datetime import date
from decimal import Decimal

from app.services import monthly_report as mr


def _party(client, **kw):
    return client.post("/api/party", json=kw).json()


def _seed_month(client):
    """One completed order, one expense and one transfer, all in June 2026."""
    biz = _party(client, name="AI.R", is_business=True)
    supplier = _party(client, name="Amazon", is_supplier=True)
    worker = _party(client, name="Alice", is_worker=True)
    loc = client.post("/api/location", json={"name": "Chic"}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    comp = client.post("/api/composition", json={
        "code": "001", "name": "Arco Maxi", "standard_price": "100.00"}).json()

    o = client.post("/api/order", json={
        "location_id": loc["location_id"], "state": "confirmed", "date": "2026-06-10",
        "total_price": "200.00",
        "items": [{"composition_id": comp["composition_id"], "quantity": 2, "unit_price": "100.00"}]}).json()
    client.patch(f"/api/order/{o['customer_order_id']}", json={"state": "completed"})

    client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-06-05",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 10,
                   "unit_cost": "6.00", "description": "Palloncini"}]})
    client.post("/api/money_transfer", json={
        "from_party_id": biz["party_id"], "to_party_id": worker["party_id"],
        "date": "2026-06-20", "amount": "50.00"})


def test_report_totals_and_snapshot(client):
    _seed_month(client)
    # A closed month (June, before today) is auto-frozen on listing.
    rows = client.get("/api/monthly_report").json()
    june = next(r for r in rows if r["year"] == 2026 and r["month"] == 6)
    assert june["status"] == "final"
    assert june["label"] == "June 2026"
    assert june["revenue_total"] == "200.00"
    assert june["expense_total"] == "60.00"
    assert june["profit_total"] == "140.00"
    assert june["transfer_total"] == "50.00"
    assert june["order_count"] == 1
    assert june["expense_count"] == 1
    assert june["transfer_count"] == 1


def test_pdf_downloads(client):
    _seed_month(client)
    client.get("/api/monthly_report")  # materialize
    r = client.get("/api/monthly_report/2026/6/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_regenerate_is_idempotent(client):
    _seed_month(client)
    client.get("/api/monthly_report")
    a = client.post("/api/monthly_report/2026/6/generate").json()
    b = client.post("/api/monthly_report/2026/6/generate").json()
    assert a["monthly_report_id"] == b["monthly_report_id"]  # upsert, not duplicate
    assert b["revenue_total"] == "200.00"


def _app_db():
    """A session on the same database the test client talks to."""
    from contextlib import contextmanager

    from app.db.session import get_db
    from app.main import app

    @contextmanager
    def cm():
        gen = app.dependency_overrides[get_db]()
        db = next(gen)
        try:
            yield db
        finally:
            gen.close()
    return cm()


def _add_transfer(client, amount):
    parties = {p["name"]: p["party_id"] for p in client.get("/api/party").json()}
    client.post("/api/money_transfer", json={
        "from_party_id": parties["AI.R"], "to_party_id": parties["Alice"],
        "date": "2026-06-21", "amount": amount})


def test_report_never_changes_unless_regenerate_is_pressed(client):
    _seed_month(client)
    first = client.get("/api/monthly_report").json()
    june = next(r for r in first if r["month"] == 6)
    assert june["has_pdf"] is True
    pdf_before = client.get("/api/monthly_report/2026/6/pdf").content

    # The underlying data changes afterwards...
    _add_transfer(client, "99.00")

    # ...but listing, re-listing and downloading (many times) leave the report untouched.
    for _ in range(3):
        rows = client.get("/api/monthly_report").json()
        again = next(r for r in rows if r["month"] == 6)
        assert again["transfer_total"] == "50.00"
        assert again["generated_at"] == june["generated_at"]
        assert client.get("/api/monthly_report/2026/6/pdf").content == pdf_before

    # Only the explicit regenerate picks up the new data.
    regen = client.post("/api/monthly_report/2026/6/generate").json()
    assert regen["transfer_total"] == "149.00"
    assert client.get("/api/monthly_report/2026/6/pdf").content != pdf_before


def test_old_template_version_does_not_trigger_regeneration(client):
    from app.db.models import MonthlyReport
    _seed_month(client)
    client.get("/api/monthly_report")
    with _app_db() as db:
        row = db.query(MonthlyReport).filter_by(year=2026, month=6).one()
        row.template_version = 0  # as if the layout had changed since
        db.commit()
    before = client.get("/api/monthly_report").json()
    after = client.get("/api/monthly_report").json()
    assert before == after
    assert next(r for r in after if r["month"] == 6)["generated_at"] == \
        next(r for r in before if r["month"] == 6)["generated_at"]


def test_download_never_generates_a_missing_pdf(client):
    from app.db.models import MonthlyReportFile
    _seed_month(client)
    client.get("/api/monthly_report")
    with _app_db() as db:
        db.query(MonthlyReportFile).delete()
        db.commit()
    assert client.get("/api/monthly_report/2026/6/pdf").status_code == 404
    rows = client.get("/api/monthly_report").json()
    assert next(r for r in rows if r["month"] == 6)["has_pdf"] is False
    assert client.get("/api/monthly_report/2026/6/pdf").status_code == 404  # still not regenerated




def test_order_contents_includes_colours_and_numbers(client, db_session):
    # The report's order description names compositions, colours and numbers so
    # each revenue line is identifiable, not just an amount.
    from app.db.models import (
        Color, Composition, CustomerOrder, Location, OrderItem,
        OrderItemColor, OrderItemNumber, RequiredItem,
    )
    loc = Location(name="Serra")
    comp = Composition(code="010", name="Nuvoletta", standard_price=30)
    white = Color(code="001", name="Bianco")
    gold = Color(code="088", name="Oro")
    num_item = RequiredItem(name="Palloncino numero 80", unit="piece", is_number=True)
    db_session.add_all([loc, comp, white, gold, num_item])
    db_session.flush()
    o = CustomerOrder(location_id=loc.location_id, state="completed",
                      date=date(2026, 6, 15), total_price=30)
    db_session.add(o); db_session.flush()
    it = OrderItem(customer_order_id=o.customer_order_id,
                   composition_id=comp.composition_id, quantity=1, unit_price=30)
    db_session.add(it); db_session.flush()
    db_session.add(OrderItemColor(order_item_id=it.order_item_id, color_id=white.color_id))
    db_session.add(OrderItemNumber(order_item_id=it.order_item_id,
                                   required_item_id=num_item.required_item_id,
                                   color_id=gold.color_id, digit="8"))
    db_session.commit()

    data = mr.build_data(db_session, 2026, 6)
    contents = data["revenue_rows"][0]["contents"]
    assert "Nuvoletta" in contents
    assert "Bianco" in contents
    assert "n.8" in contents and "Oro" in contents
