"""Transactional entry tests: order creation, completion -> consumption, expense, work."""
from datetime import date, timedelta
from decimal import Decimal


def _seed_bom(client):
    """Create location, colours, a required_item and a composition with a BOM.
    Returns useful ids."""
    loc = client.post("/api/location", json={"name": "CHIC"}).json()
    red = client.post("/api/color", json={"code": "045", "name": "Rosso"}).json()
    white = client.post("/api/color", json={"code": "001", "name": "Bianco"}).json()
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()
    comp = client.post("/api/composition", json={
        "code": "001", "name": "Arco", "standard_price": "85.00"}).json()
    client.put(f"/api/composition/{comp['composition_id']}/bom",
               json=[{"required_item_id": item["required_item_id"], "quantity": "100"}])
    return {
        "location_id": loc["location_id"],
        "red": red["color_id"], "white": white["color_id"],
        "required_item_id": item["required_item_id"],
        "composition_id": comp["composition_id"],
    }


def test_order_create_and_complete_generates_consumption(client):
    ids = _seed_bom(client)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "170.00",
        "items": [{
            "composition_id": ids["composition_id"], "quantity": 2, "unit_price": "85.00",
            "colors": [
                {"color_id": ids["red"], "color_percentage": "70"},
                {"color_id": ids["white"], "color_percentage": "30"},
            ],
        }],
    })
    assert order.status_code == 201, order.text
    order_id = order.json()["customer_order_id"]
    assert len(order.json()["items"][0]["colors"]) == 2

    # Complete -> consumption. 100 * 2 = 200, split 70/30 = 140 / 60.
    done = client.patch(f"/api/order/{order_id}", json={"state": "completed"})
    assert done.status_code == 200
    assert done.json()["state"] == "completed"

    stock = client.get("/api/stock").json()
    by_color = {r["color_name"]: r["quantity"] for r in stock}
    assert by_color["Rosso"] == -140
    assert by_color["Bianco"] == -60

    # The consumption movement is dated as the order, not today.
    updates = client.get("/api/inventory_update").json()
    usage = [u for u in updates if u["type"] == "order_usage"]
    assert len(usage) == 1
    assert usage[0]["date"] == "2026-06-15"


def test_order_delete_removes_order_and_consumption(client):
    ids = _seed_bom(client)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "85.00",
        "items": [{"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "85.00",
                   "colors": [{"color_id": ids["red"], "color_percentage": "100"}]}],
    }).json()
    oid = order["customer_order_id"]
    client.patch(f"/api/order/{oid}", json={"state": "completed"})
    assert any(u["type"] == "order_usage" for u in client.get("/api/inventory_update").json())

    assert client.delete(f"/api/order/{oid}").status_code == 200
    assert client.get(f"/api/order/{oid}").status_code == 404
    assert not any(u["type"] == "order_usage" for u in client.get("/api/inventory_update").json())
    assert client.delete(f"/api/order/{oid}").status_code == 404


def test_order_leaving_completed_removes_consumption(client):
    # Completing generates stock usage; moving the order back out of 'completed'
    # (here -> cancelled) must undo that usage, or the stock stays wrongly depleted.
    ids = _seed_bom(client)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "85.00",
        "items": [{"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "85.00",
                   "colors": [{"color_id": ids["red"], "color_percentage": "100"}]}],
    }).json()
    oid = order["customer_order_id"]

    client.patch(f"/api/order/{oid}", json={"state": "completed"})
    assert {r["color_name"]: r["quantity"] for r in client.get("/api/stock").json()}["Rosso"] == -100
    assert any(u["type"] == "order_usage" for u in client.get("/api/inventory_update").json())

    # Leave 'completed' -> consumption is reverted, stock is back to zero.
    assert client.patch(f"/api/order/{oid}", json={"state": "cancelled"}).status_code == 200
    assert not any(u["type"] == "order_usage" for u in client.get("/api/inventory_update").json())
    assert all(r["quantity"] == 0 for r in client.get("/api/stock").json())


def test_stock_forecast_levels_from_confirmed_orders(client):
    """Red > orange > yellow, derived from confirmed orders' future consumption."""
    loc = client.post("/api/location", json={"name": "CHIC"}).json()
    red = client.post("/api/color", json={"code": "045", "name": "Rosso"}).json()["color_id"]
    ora = client.post("/api/color", json={"code": "004", "name": "Arancio"}).json()["color_id"]
    yel = client.post("/api/color", json={"code": "002", "name": "Giallo"}).json()["color_id"]
    # minimum 150 on the material; BOM of 50 per unit so order quantity scales consumption.
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True,
        "minimum_safe_quantity": 150}).json()
    rid = item["required_item_id"]
    comp = client.post("/api/composition", json={
        "code": "001", "name": "Arco", "standard_price": "85.00"}).json()["composition_id"]
    client.put(f"/api/composition/{comp}/bom",
               json=[{"required_item_id": rid, "quantity": "50"}])

    # Start every colour at 200 units.
    client.post("/api/inventory_update", json={
        "type": "gift", "date": "2026-01-01",
        "items": [{"required_item_id": rid, "color_id": c, "quantity_change": 200}
                  for c in (red, ora, yel)]})

    soon = (date.today() + timedelta(days=3)).isoformat()      # within 10 days
    later = (date.today() + timedelta(days=30)).isoformat()    # beyond 10 days

    def order(color_id, qty, when):
        return client.post("/api/order", json={
            "location_id": loc["location_id"], "state": "confirmed",
            "date": when, "total_price": "0.00",
            "items": [{"composition_id": comp, "quantity": qty, "unit_price": "0.00",
                       "colors": [{"color_id": color_id, "color_percentage": "100"}]}]})

    order(red, 5, soon)    # 250 within 10d -> 200-250 < 0            => red
    order(ora, 2, soon)    # 100 within 10d -> 200-100=100 (<150)     => orange
    order(yel, 2, later)   # 100 future only -> after10 ok, all<150   => yellow

    levels = {r["color_name"]: r["level"] for r in client.get("/api/stock").json()
              if r["required_item_name"] == "Palloncino grande"}
    assert levels["Rosso"] == "red"
    assert levels["Arancio"] == "orange"
    assert levels["Giallo"] == "yellow"


def test_order_numbers_consume_by_digit_colour(client):
    # Numbers are consumed from the per-order detail (digit/colour/size),
    # independent of the item's balloon colour mix.
    loc = client.post("/api/location", json={"name": "CHIC"}).json()
    gold = client.post("/api/color", json={"code": "088", "name": "Oro"}).json()
    silver = client.post("/api/color", json={"code": "089", "name": "Argento"}).json()
    num80 = client.post("/api/required_item", json={
        "name": "Palloncino numero 80", "unit": "piece", "used_color": True,
        "is_number": True}).json()
    comp = client.post("/api/composition", json={
        "code": "014", "name": "Numero Maxi", "standard_price": "25.00"}).json()

    # Age "18": digit 1 with colour omitted (defaults to silver, no gold in the
    # mix), digit 8 explicitly gold.
    order = client.post("/api/order", json={
        "location_id": loc["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "50.00",
        "items": [{
            "composition_id": comp["composition_id"], "quantity": 1, "unit_price": "50.00",
            "numbers": [
                {"required_item_id": num80["required_item_id"], "digit": "1"},
                {"required_item_id": num80["required_item_id"], "digit": "8",
                 "color_id": gold["color_id"]},
            ],
        }],
    })
    assert order.status_code == 201, order.text
    nums = order.json()["items"][0]["numbers"]
    assert len(nums) == 2
    # Omitted colour defaulted to silver; explicit colour kept.
    assert {n["digit"]: n["color_id"] for n in nums} == {
        "1": silver["color_id"], "8": gold["color_id"]}

    client.patch(f"/api/order/{order.json()['customer_order_id']}", json={"state": "completed"})
    stock = client.get("/api/stock").json()
    by_key = {(r["color_name"], r["variant"]): r["quantity"] for r in stock}
    assert by_key[("Argento", "1")] == -1
    assert by_key[("Oro", "8")] == -1


def _number_comp(client, code, name, bom_qty):
    """Location, gold + silver colours, a number material and a composition needing
    `bom_qty` numbers. Returns useful ids."""
    loc = client.post("/api/location", json={"name": "CHIC"}).json()
    gold = client.post("/api/color", json={"code": "088", "name": "Oro"}).json()
    silver = client.post("/api/color", json={"code": "089", "name": "Argento"}).json()
    num80 = client.post("/api/required_item", json={
        "name": "Palloncino numero 80", "unit": "piece", "used_color": True,
        "is_number": True}).json()
    comp = client.post("/api/composition", json={
        "code": code, "name": name, "standard_price": "25.00"}).json()
    client.put(f"/api/composition/{comp['composition_id']}/bom",
               json=[{"required_item_id": num80["required_item_id"], "quantity": str(bom_qty)}])
    return {"location_id": loc["location_id"], "composition_id": comp["composition_id"],
            "gold": gold["color_id"], "silver": silver["color_id"],
            "num_size": num80["required_item_id"]}


def test_number_composition_defaults_to_18_silver(client):
    # A two-number composition saved without digits defaults to "18" (1 and 8),
    # silver when the mix has no gold. The digits are stored (visible/editable)
    # and the order confirms/completes with no blocking.
    ids = _number_comp(client, "012", "Nuvoletta con numero", 2)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "50.00",
        "items": [{"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "50.00"}],
    })
    assert order.status_code == 201, order.text
    nums = order.json()["items"][0]["numbers"]
    assert {(n["digit"], n["color_id"]) for n in nums} == {
        ("1", ids["silver"]), ("8", ids["silver"])}

    client.patch(f"/api/order/{order.json()['customer_order_id']}", json={"state": "completed"})
    by_key = {(r["color_name"], r["variant"]): r["quantity"]
              for r in client.get("/api/stock").json()}
    assert by_key[("Argento", "1")] == -1
    assert by_key[("Argento", "8")] == -1


def test_single_digit_number_composition_defaults_to_one_digit(client):
    # A single-number composition defaults to just "1" (cycling 1,8 -> no double count).
    ids = _number_comp(client, "NMA", "Numero ad Aria", 1)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "20.00",
        "items": [{"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "20.00"}]}).json()
    assert [n["digit"] for n in order["items"][0]["numbers"]] == ["1"]


def test_number_default_colour_is_gold_when_mix_has_gold(client):
    # Defaulted "18" digits take gold when the item's balloon mix includes gold.
    ids = _number_comp(client, "012", "Nuvoletta con numero", 2)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "50.00",
        "items": [{"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "50.00",
                   "colors": [{"color_id": ids["gold"]}]}],
    })
    assert order.status_code == 201, order.text
    nums = order.json()["items"][0]["numbers"]
    assert {(n["digit"], n["color_id"]) for n in nums} == {("1", ids["gold"]), ("8", ids["gold"])}
    client.patch(f"/api/order/{order.json()['customer_order_id']}", json={"state": "completed"})
    by_key = {(r["color_name"], r["variant"]): r["quantity"]
              for r in client.get("/api/stock").json()}
    assert by_key[("Oro", "1")] == -1
    assert by_key[("Oro", "8")] == -1


def test_completion_splits_colours_evenly_when_no_percentages(client):
    # Colours listed without percentages -> even split (here 100/2 = 50/50).
    ids = _seed_bom(client)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "85.00",
        "items": [{
            "composition_id": ids["composition_id"], "quantity": 1, "unit_price": "85.00",
            "colors": [{"color_id": ids["red"]}, {"color_id": ids["white"]}],
        }],
    }).json()
    client.patch(f"/api/order/{order['customer_order_id']}", json={"state": "completed"})

    stock = client.get("/api/stock").json()
    by_color = {r["color_name"]: r["quantity"] for r in stock}
    assert by_color == {"Rosso": -50, "Bianco": -50}


def test_completion_is_idempotent(client):
    ids = _seed_bom(client)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed", "date": "2026-06-15",
        "total_price": "85.00",
        "items": [{"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "85.00",
                   "colors": [{"color_id": ids["red"], "color_percentage": "100"}]}],
    }).json()
    oid = order["customer_order_id"]
    client.patch(f"/api/order/{oid}", json={"state": "completed"})
    client.patch(f"/api/order/{oid}", json={"state": "completed", "comment": "again"})
    stock = client.get("/api/stock").json()
    # 100 consumed once, not twice.
    assert sum(r["quantity"] for r in stock) == -100


def test_items_locked_only_when_cancelled(client):
    # Completed orders remain editable (see test_edit_completed_order_*); only
    # cancelled orders reject item edits.
    ids = _seed_bom(client)
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "completed", "date": "2026-06-15",
        "total_price": "85.00",
        "items": [{"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "85.00"}],
    }).json()
    oid = order["customer_order_id"]
    ok = client.put(f"/api/order/{oid}/items",
                    json=[{"composition_id": ids["composition_id"], "quantity": 5,
                           "unit_price": "85.00"}])
    assert ok.status_code == 200

    client.patch(f"/api/order/{oid}", json={"state": "cancelled"})
    blocked = client.put(f"/api/order/{oid}/items",
                         json=[{"composition_id": ids["composition_id"], "quantity": 5,
                                "unit_price": "85.00"}])
    assert blocked.status_code == 400


def test_expense_with_items(client):
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    supplier = client.post("/api/party", json={"name": "Amazon", "is_supplier": True}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    expense = client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-06-01",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 5,
                   "unit_cost": "6.00", "description": "palloncini"}],
    })
    assert expense.status_code == 201, expense.text
    assert expense.json()["items"][0]["unit_cost"] == "6.00"

    # payer == payee -> 400
    bad = client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": biz["party_id"],
        "date": "2026-06-01", "items": []})
    assert bad.status_code == 400


def test_expense_with_product_refills_stock(client):
    # A product line on an expense raises stock at (required_item, colour).
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    supplier = client.post("/api/party", json={"name": "Amazon", "is_supplier": True}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    red = client.post("/api/color", json={"code": "045", "name": "Rosso"}).json()
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()
    product = client.post("/api/product", json={
        "required_item_id": item["required_item_id"], "color_id": red["color_id"],
        "name": "Gemar 30cm Rosso"}).json()

    expense = client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-06-01",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 500,
                   "unit_cost": "0.10", "product_id": product["product_id"]}],
    })
    assert expense.status_code == 201, expense.text

    stock = client.get("/api/stock").json()
    red_rows = [r for r in stock if r["color_name"] == "Rosso"]
    assert len(red_rows) == 1
    assert red_rows[0]["quantity"] == 500

    # A non-product line adds no stock.
    expense2 = client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-06-02",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 1,
                   "unit_cost": "20.00", "description": "parcheggio"}],
    })
    assert expense2.status_code == 201
    stock = client.get("/api/stock").json()
    assert sum(r["quantity"] for r in stock) == 500  # unchanged by the parking line


def test_order_total_is_derived_from_lines(client):
    # The stored total is always the sum of the line totals (unit×qty−discount
    # + colour surcharges); a bogus provided total is overridden.
    ids = _seed_bom(client)
    o = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed", "date": "2026-06-15",
        "total_price": "999.00",  # deliberately wrong
        "items": [{"composition_id": ids["composition_id"], "quantity": 2, "unit_price": "50.00",
                   "discount": "10",
                   "colors": [{"color_id": ids["red"], "color_surcharge": "8.00"}]}],
    }).json()
    # 50×2×0.9 + 8×0.9 = 90 + 7.20 = 97.20
    assert abs(float(o["total_price"]) - 97.20) < 0.005

    # Replacing items recomputes the total.
    r = client.put(f"/api/order/{o['customer_order_id']}/items", json=[
        {"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "100.00"}]).json()
    assert abs(float(r["total_price"]) - 100.00) < 0.005


def test_edit_completed_order_rebuilds_consumption(client):
    # A completed order can be edited; its stock consumption is recomputed.
    ids = _seed_bom(client)  # composition BOM: 100 units of a coloured item
    order = client.post("/api/order", json={
        "location_id": ids["location_id"], "state": "confirmed",
        "date": "2026-06-15", "total_price": "85.00",
        "items": [{"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "85.00",
                   "colors": [{"color_id": ids["red"], "color_percentage": "100"}]}],
    }).json()
    oid = order["customer_order_id"]
    client.patch(f"/api/order/{oid}", json={"state": "completed"})
    stock = {r["color_name"]: r["quantity"] for r in client.get("/api/stock").json()}
    assert stock["Rosso"] == -100  # 100 × 1

    # Edit the completed order: quantity 3 now -> consumption rebuilt to -300.
    r = client.put(f"/api/order/{oid}/items", json=[
        {"composition_id": ids["composition_id"], "quantity": 3, "unit_price": "85.00",
         "colors": [{"color_id": ids["red"], "color_percentage": "100"}]}])
    assert r.status_code == 200, r.text
    stock = {r["color_name"]: r["quantity"] for r in client.get("/api/stock").json()}
    assert stock["Rosso"] == -300  # not -400: the old -100 movement was replaced

    # Only one order_usage movement remains (no orphan/double count).
    usage = [u for u in client.get("/api/inventory_update").json() if u["type"] == "order_usage"]
    assert len(usage) == 1

    # A cancelled order cannot have its items edited.
    client.patch(f"/api/order/{oid}", json={"state": "cancelled"})
    blocked = client.put(f"/api/order/{oid}/items", json=[
        {"composition_id": ids["composition_id"], "quantity": 1, "unit_price": "85.00"}])
    assert blocked.status_code == 400


def test_listing_orders_auto_completes_past_confirmed(client):
    # A confirmed order whose event date has passed is auto-completed when orders
    # are listed; a draft or a today/future order is left alone.
    from datetime import date, timedelta
    loc = client.post("/api/location", json={"name": "Chic"}).json()
    comp = client.post("/api/composition", json={
        "code": "001", "name": "Arco", "standard_price": "85.00"}).json()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()

    def mk(state, when):
        return client.post("/api/order", json={
            "location_id": loc["location_id"], "state": state, "date": when,
            "total_price": "85.00",
            "items": [{"composition_id": comp["composition_id"], "quantity": 1,
                       "unit_price": "85.00"}]}).json()["customer_order_id"]

    past_confirmed = mk("confirmed", yesterday)
    past_draft = mk("draft", yesterday)
    today_confirmed = mk("confirmed", today)

    orders = {o["customer_order_id"]: o["state"] for o in client.get("/api/order").json()}
    assert orders[past_confirmed] == "completed"   # closed automatically
    assert orders[past_draft] == "draft"           # drafts are not commitments
    assert orders[today_confirmed] == "confirmed"  # event day not yet past


def test_edit_expense_with_refill_rebuilds_stock(client):
    # Editing an expense that generated a refill must not 500 (the purchase
    # movement references the item rows): the refill is rebuilt from new lines.
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    supplier = client.post("/api/party", json={"name": "Amazon", "is_supplier": True}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    green = client.post("/api/color", json={"code": "013", "name": "Verde"}).json()
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()
    product = client.post("/api/product", json={
        "required_item_id": item["required_item_id"], "color_id": green["color_id"],
        "name": "Gemar 30cm Verde", "package_quantity": 100}).json()

    expense = client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-08-31",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 2,
                   "unit_cost": "6.00", "product_id": product["product_id"]}],
    }).json()
    eid = expense["expense_id"]
    assert client.get("/api/stock").json()[0]["quantity"] == 200

    # 1) change only the header date — this used to 500.
    r = client.patch(f"/api/expense/{eid}", json={"date": "2026-09-01"})
    assert r.status_code == 200, r.text
    assert r.json()["date"] == "2026-09-01"

    # 2) replace the items (buy 3 packs now) — refill rebuilt, stock follows.
    r = client.put(f"/api/expense/{eid}/items", json=[
        {"expense_category_id": cat["expense_category_id"], "quantity": 3,
         "unit_cost": "6.00", "product_id": product["product_id"]}])
    assert r.status_code == 200, r.text
    stock = client.get("/api/stock").json()
    assert sum(s["quantity"] for s in stock) == 300  # 3 packs × 100, old 200 gone

    # 3) drop the product line entirely — stock returns to zero, no orphan refill.
    r = client.put(f"/api/expense/{eid}/items", json=[
        {"expense_category_id": cat["expense_category_id"], "quantity": 1,
         "unit_cost": "5.00", "description": "parcheggio"}])
    assert r.status_code == 200, r.text
    assert sum(s["quantity"] for s in client.get("/api/stock").json()) == 0


def test_refill_converts_packs_to_pieces(client):
    # A product with package_quantity=100: buying 2 packs adds 200 pieces.
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    supplier = client.post("/api/party", json={"name": "Amazon", "is_supplier": True}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    blue = client.post("/api/color", json={"code": "010", "name": "Blu"}).json()
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()
    product = client.post("/api/product", json={
        "required_item_id": item["required_item_id"], "color_id": blue["color_id"],
        "name": "Gemar 30cm Blu", "package_quantity": 100}).json()
    assert product["package_quantity"] == 100

    client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-06-01",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 2,
                   "unit_cost": "6.00", "product_id": product["product_id"]}],
    })
    stock = client.get("/api/stock").json()
    blue_rows = [r for r in stock if r["color_name"] == "Blu"]
    assert len(blue_rows) == 1
    assert blue_rows[0]["quantity"] == 200


def test_number_purchase_refills_by_digit(client):
    # A number-product expense line carrying a digit refills stock at that digit.
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    supplier = client.post("/api/party", json={"name": "SupplyCo", "is_supplier": True}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    gold = client.post("/api/color", json={"code": "088", "name": "Oro"}).json()
    num110 = client.post("/api/required_item", json={
        "name": "Palloncino numero 110", "unit": "piece", "used_color": True,
        "is_number": True}).json()
    product = client.post("/api/product", json={
        "required_item_id": num110["required_item_id"], "color_id": gold["color_id"],
        "name": "Numero 110cm Oro"}).json()  # package_quantity defaults to 1

    client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-06-01",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 5,
                   "unit_cost": "2.00", "product_id": product["product_id"], "variant": "8"}],
    })
    stock = client.get("/api/stock").json()
    by_key = {(r["color_name"], r["variant"]): r["quantity"] for r in stock}
    assert by_key[("Oro", "8")] == 5


def test_work_entry_and_end_before_start_rejected(client):
    worker = client.post("/api/party", json={"name": "Alice", "is_worker": True}).json()
    ok = client.post("/api/work", json={
        "party_id": worker["party_id"], "start_at": "2026-06-15T08:00:00",
        "end_at": "2026-06-15T10:30:00", "tasks_accomplished": "installazione"})
    assert ok.status_code == 201
    bad = client.post("/api/work", json={
        "party_id": worker["party_id"], "start_at": "2026-06-15T10:00:00",
        "end_at": "2026-06-15T08:00:00"})
    assert bad.status_code == 400


def test_manual_inventory_update(client):
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": False}).json()
    rid = item["required_item_id"]

    # recount = absolute: the real count is 500 -> stock becomes 500.
    r = client.post("/api/inventory_update", json={
        "type": "recount", "date": "2026-06-01",
        "items": [{"required_item_id": rid, "quantity_change": 500}]})
    assert r.status_code == 201
    assert client.get("/api/stock").json()[0]["quantity"] == 500

    # loss = enter a positive magnitude, stored as negative -> 500 - 20 = 480.
    client.post("/api/inventory_update", json={
        "type": "loss", "date": "2026-06-02",
        "items": [{"required_item_id": rid, "quantity_change": 20}]})
    assert client.get("/api/stock").json()[0]["quantity"] == 480

    # gift = positive -> 480 + 30 = 510.
    client.post("/api/inventory_update", json={
        "type": "gift", "date": "2026-06-03",
        "items": [{"required_item_id": rid, "quantity_change": 30}]})
    assert client.get("/api/stock").json()[0]["quantity"] == 510

    # a later recount to 100 reconciles down (delta -410) -> 100.
    client.post("/api/inventory_update", json={
        "type": "recount", "date": "2026-06-04",
        "items": [{"required_item_id": rid, "quantity_change": 100}]})
    assert client.get("/api/stock").json()[0]["quantity"] == 100

    # purchase/consumption can't be created manually (come from expenses/orders).
    bad = client.post("/api/inventory_update", json={
        "type": "purchase", "date": "2026-06-05",
        "items": [{"required_item_id": rid, "quantity_change": 100}]})
    assert bad.status_code == 400


def test_work_bulk_creates_one_session_per_worker(client):
    a = client.post("/api/party", json={"name": "Alice", "is_worker": True}).json()
    b = client.post("/api/party", json={"name": "Bob", "is_worker": True}).json()
    c = client.post("/api/party", json={"name": "Carol", "is_worker": True}).json()
    r = client.post("/api/work/bulk", json={
        "party_ids": [a["party_id"], b["party_id"], c["party_id"], a["party_id"]],  # dup ignored
        "start_at": "2026-06-15T08:00:00", "end_at": "2026-06-15T13:00:00",
        "break_minutes": 30, "tasks_accomplished": "setup"})
    assert r.status_code == 201, r.text
    created = r.json()
    assert len(created) == 3  # de-duplicated: one row per distinct worker
    assert {w["party_id"] for w in created} == {a["party_id"], b["party_id"], c["party_id"]}
    assert all(w["break_minutes"] == 30 for w in created)
    assert len(client.get("/api/work").json()) == 3


def test_delete_expense_removes_its_refill(client):
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    sup = client.post("/api/party", json={"name": "Amazon", "is_supplier": True}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    item = client.post("/api/required_item", json={"name": "Palloncino grande", "unit": "piece"}).json()
    prod = client.post("/api/product", json={
        "required_item_id": item["required_item_id"], "name": "Gemar", "package_quantity": 100}).json()
    e = client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": sup["party_id"], "date": "2026-06-01",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 2,
                   "unit_cost": "6.00", "product_id": prod["product_id"]}]}).json()
    assert client.get("/api/stock").json()[0]["quantity"] == 200
    # the auto purchase movement can't be deleted directly
    pur = next(u for u in client.get("/api/inventory_update").json() if u["type"] == "purchase")
    assert client.delete(f"/api/inventory_update/{pur['inventory_update_id']}").status_code == 400
    # deleting the expense removes the refill -> stock back to 0
    assert client.delete(f"/api/expense/{e['expense_id']}").status_code == 200
    assert client.get("/api/expense").json() == []
    assert sum(s["quantity"] for s in client.get("/api/stock").json()) == 0


def test_delete_stock_update(client):
    item = client.post("/api/required_item", json={"name": "Palloncino grande", "unit": "piece"}).json()
    u = client.post("/api/inventory_update", json={
        "type": "gift", "date": "2026-06-01",
        "items": [{"required_item_id": item["required_item_id"], "quantity_change": 50}]}).json()
    assert client.get("/api/stock").json()[0]["quantity"] == 50
    assert client.delete(f"/api/inventory_update/{u['inventory_update_id']}").status_code == 200
    assert sum(s["quantity"] for s in client.get("/api/stock").json()) == 0

def test_edit_recount_and_gift(client):
    """Editing a manual movement (PATCH) re-derives the stock correctly."""
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()
    rid = item["required_item_id"]
    red = client.post("/api/color", json={"code": "045", "name": "Rosso"}).json()["color_id"]

    def red_stock():
        return next(r["quantity"] for r in client.get("/api/stock").json()
                    if r["required_item_name"] == "Palloncino grande" and r["color_name"] == "Rosso")

    # recount sets the counted absolute (=100), then editing it to 60 => stock 60
    upd = client.post("/api/inventory_update", json={
        "type": "recount", "date": "2026-10-04",
        "items": [{"required_item_id": rid, "color_id": red, "quantity_change": 100}]}).json()
    uid = upd["inventory_update_id"]
    assert red_stock() == 100
    r = client.patch(f"/api/inventory_update/{uid}", json={
        "type": "recount", "date": "2026-10-04",
        "items": [{"required_item_id": rid, "color_id": red, "quantity_change": 60}]})
    assert r.status_code == 200
    assert red_stock() == 60

    # editing a gift magnitude (10 -> 25) is a +25 movement
    g = client.post("/api/inventory_update", json={
        "type": "gift", "date": "2026-10-04",
        "items": [{"required_item_id": rid, "quantity_change": 10}]}).json()
    assert client.patch(f"/api/inventory_update/{g['inventory_update_id']}", json={
        "type": "gift", "date": "2026-10-04",
        "items": [{"required_item_id": rid, "quantity_change": 25}]}).status_code == 200
    assert next(r["quantity"] for r in client.get("/api/stock").json()
                if r["required_item_name"] == "Palloncino grande" and r["color_name"] is None) == 25


def test_edit_auto_movement_rejected(client):
    """Purchase/consumption movements can't be edited via PATCH."""
    biz = client.post("/api/party", json={"name": "AI.R", "is_customer": True}).json()
    supplier = client.post("/api/party", json={"name": "Amazon", "is_supplier": True}).json()
    cat = client.post("/api/expense_category", json={"name": "materials"}).json()
    item = client.post("/api/required_item", json={"name": "Palloncino grande", "unit": "piece"}).json()
    prod = client.post("/api/product", json={
        "name": "Bag", "required_item_id": item["required_item_id"]}).json()
    client.post("/api/expense", json={
        "paid_by_party_id": biz["party_id"], "paid_to_party_id": supplier["party_id"],
        "date": "2026-06-01",
        "items": [{"expense_category_id": cat["expense_category_id"], "quantity": 1,
                   "unit_cost": "6.00", "product_id": prod["product_id"]}]})
    pur = next(u for u in client.get("/api/inventory_update").json() if u["type"] == "purchase")
    assert client.patch(f"/api/inventory_update/{pur['inventory_update_id']}", json={
        "type": "recount", "date": "2026-06-01",
        "items": [{"required_item_id": item["required_item_id"], "quantity_change": 5}]}).status_code == 400
