"""Compositional metrics engine + /api/metrics endpoint tests."""


def _setup(client):
    loc = client.post("/api/location", json={"name": "CHIC"}).json()
    loc2 = client.post("/api/location", json={"name": "SERRA"}).json()
    comp = client.post("/api/composition", json={
        "code": "001", "name": "Arco", "standard_price": "100.00"}).json()
    worker = client.post("/api/party", json={"name": "Alice", "is_worker": True}).json()

    def order(state, dateval, total, location):
        client.post("/api/order", json={
            "location_id": location, "state": state, "date": dateval, "total_price": total,
            "items": [{"composition_id": comp["composition_id"], "quantity": 1, "unit_price": total}]})

    # July: 300 completed (CHIC) + 100 completed (SERRA) + 999 draft (excluded)
    order("completed", "2026-07-05", "300.00", loc["location_id"])
    order("completed", "2026-07-20", "100.00", loc2["location_id"])
    order("draft", "2026-07-21", "999.00", loc["location_id"])
    # August: 200 completed
    order("completed", "2026-08-10", "200.00", loc["location_id"])
    return {"loc": loc["location_id"], "loc2": loc2["location_id"], "worker": worker["party_id"]}


def test_scalar_revenue_completed_only(client):
    _setup(client)
    r = client.get("/api/metrics/revenue?start=2026-07-01&end=2026-07-31").json()
    assert r["value"] == 400.0  # 300 + 100, draft excluded


def test_revenue_and_items_by_composition(client):
    _setup(client)
    # Revenue is item-attributed, so it breaks down by composition and matches the total.
    r = client.get("/api/metrics/revenue?start=2026-07-01&end=2026-07-31&group_by=composition").json()
    assert {p["label"]: p["value"] for p in r["series"]} == {"Arco": 400.0}
    s = client.get("/api/metrics/items_sold?start=2026-07-01&end=2026-07-31").json()
    assert s["value"] == 2  # two completed July orders, qty 1 each


def test_multi_value_scope(client):
    ids = _setup(client)
    both = client.get(f"/api/metrics/revenue?start=2026-07-01&end=2026-07-31"
                      f"&scope_location={ids['loc']}&scope_location={ids['loc2']}").json()
    assert both["value"] == 400.0
    one = client.get(f"/api/metrics/revenue?start=2026-07-01&end=2026-07-31"
                     f"&scope_location={ids['loc']}").json()
    assert one["value"] == 300.0  # CHIC only


def test_series_by_month(client):
    _setup(client)
    r = client.get("/api/metrics/revenue?start=2026-07-01&end=2026-08-31&group_by=month").json()
    by_month = {p["key"]: p["value"] for p in r["series"]}
    assert by_month == {"2026-07": 400.0, "2026-08": 200.0}


def test_series_by_location_with_labels(client):
    _setup(client)
    r = client.get("/api/metrics/revenue?start=2026-07-01&end=2026-07-31&group_by=location").json()
    by_loc = {p["label"]: p["value"] for p in r["series"]}
    assert by_loc == {"CHIC": 300.0, "SERRA": 100.0}


def test_scope_filter(client):
    ids = _setup(client)
    r = client.get(f"/api/metrics/revenue?start=2026-07-01&end=2026-07-31&scope_location={ids['loc']}").json()
    assert r["value"] == 300.0


def test_profit_is_revenue_minus_costs(client):
    ids = _setup(client)
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    sup = client.post("/api/party", json={"name": "Amazon", "is_supplier": True}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": sup["party_id"],
        "date": "2026-07-08",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 1,
                   "unit_cost": "150.00"}]})
    r = client.get("/api/metrics/profit?start=2026-07-01&end=2026-07-31").json()
    assert r["value"] == 250.0  # 400 revenue - 150 costs


def test_compare_previous_period(client):
    _setup(client)
    # August vs July (equal length months handled by previous_period on the range).
    r = client.get("/api/metrics/revenue?start=2026-08-01&end=2026-08-31&compare=true").json()
    assert r["current"] == 200.0
    assert r["previous"] == 400.0  # July
    assert r["delta"] == -200.0
    assert r["pct_change"] == -50.0


def test_hours_by_worker(client):
    ids = _setup(client)
    client.post("/api/work", json={
        "party_id": ids["worker"], "start_at": "2026-07-15T08:00:00",
        "end_at": "2026-07-15T12:00:00"})  # 4h
    r = client.get("/api/metrics/hours?start=2026-07-01&end=2026-07-31&group_by=worker").json()
    assert r["series"][0]["label"] == "Alice"
    assert r["series"][0]["value"] == 4.0


def test_unknown_metric_404(client):
    r = client.get("/api/metrics/bogus?start=2026-07-01&end=2026-07-31")
    assert r.status_code == 404
