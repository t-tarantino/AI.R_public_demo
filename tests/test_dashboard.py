"""Dashboard metrics tests."""


def _party(client, **kw):
    return client.post("/api/party", json=kw).json()


def test_summary_revenue_costs_profit(client):
    loc = client.post("/api/location", json={"name": "CHIC"}).json()
    biz = _party(client, name="AI.R", is_customer=True)
    supplier = _party(client, name="Amazon", is_supplier=True)
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    comp = client.post("/api/composition", json={
        "code": "001", "name": "Arco", "standard_price": "85.00"}).json()

    # Two orders in June. Revenue counts only completed ones.
    client.post("/api/order", json={
        "location_id": loc["location_id"], "state": "completed", "date": "2026-06-10",
        "total_price": "200.00",
        "items": [{"composition_id": comp["composition_id"], "quantity": 1, "unit_price": "200.00"}]})
    client.post("/api/order", json={
        "location_id": loc["location_id"], "state": "cancelled", "date": "2026-06-12",
        "total_price": "999.00", "items": []})
    # One expense in June.
    client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-06-05",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 10,
                   "unit_cost": "6.00"}]})

    s = client.get("/api/dashboard/summary?start=2026-06-01&end=2026-06-30").json()
    assert s["revenue"] == "200.00"
    assert s["costs"] == "60.00"
    assert s["profit"] == "140.00"
    assert s["order_count"] == 1  # cancelled excluded
    assert s["avg_order_value"] == "200.00"

    # A period with nothing returns zeros.
    empty = client.get("/api/dashboard/summary?start=2026-07-01&end=2026-07-31").json()
    assert empty["revenue"] == "0.00"
    assert empty["order_count"] == 0


def test_balances_settle_via_non_business_transfer(client):
    # A client paying a worker directly settles debts through the business hub:
    # the payer's balance rises, the receiver's falls — even though neither is
    # the business.
    biz = _party(client, name="AI.R", is_business=True)
    worker = _party(client, name="Alice", is_worker=True)
    client_party = _party(client, name="Riverside Hall", is_customer=True)
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()

    # Worker fronts a €100 business expense -> business owes the worker €100.
    client.post("/api/expense", json={
        "paid_by_party_id": worker["party_id"], "paid_to_party_id": biz["party_id"],
        "date": "2026-06-01",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 1,
                   "unit_cost": "100.00", "description": "balloons"}]})

    def bal():
        return {b["name"]: float(b["amount"]) for b in client.get("/api/dashboard/balances").json()}

    assert bal().get("Alice") == 100.0
    assert "Riverside Hall" not in bal()  # no debt yet

    # The client pays the worker €100 directly.
    client.post("/api/money_transfer", json={
        "from_party_id": client_party["party_id"], "to_party_id": worker["party_id"],
        "date": "2026-06-02", "amount": "100.00"})

    after = bal()
    assert "Alice" not in after            # worker fully paid: settled
    assert after["Riverside Hall"] == 100.0        # client now owes the business €100




def test_worker_hours(client):
    worker = _party(client, name="Alice", is_worker=True)
    client.post("/api/work", json={
        "party_id": worker["party_id"], "start_at": "2026-06-15T08:00:00",
        "end_at": "2026-06-15T13:00:00", "break_minutes": 30})  # 4.5h
    s = client.get("/api/dashboard/summary?start=2026-06-01&end=2026-06-30").json()
    assert s["worker_hours"] == 4.5


def test_upcoming_orders_only_confirmed(client):
    loc = client.post("/api/location", json={"name": "CHIC"}).json()
    comp = client.post("/api/composition", json={
        "code": "001", "name": "Arco", "standard_price": "85.00"}).json()
    # A confirmed order far in the future is not "upcoming 30d"; a draft is excluded.
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=5)).isoformat()
    client.post("/api/order", json={
        "location_id": loc["location_id"], "state": "confirmed", "date": soon,
        "total_price": "100.00",
        "items": [{"composition_id": comp["composition_id"], "quantity": 1, "unit_price": "100.00"}]})
    client.post("/api/order", json={
        "location_id": loc["location_id"], "state": "draft", "date": soon, "total_price": "50.00",
        "items": []})
    upcoming = client.get("/api/dashboard/upcoming").json()
    assert len(upcoming) == 1
    assert upcoming[0]["state"] == "confirmed"
