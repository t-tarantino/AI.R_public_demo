"""Richie batch-import tests: orders (customer, discount, one-order-per-day rule,
partial commit) and expenses (parties, products, stock refill, duplicates),
plus the prompt built from the spec."""


def _seed(client):
    client.post("/api/party", json={"name": "Riverside Hall", "code_nickname": "RVH", "is_customer": True})
    client.post("/api/party", json={"name": "Mario Rossi", "is_customer": True})
    client.post("/api/party", json={"name": "Amazon", "code_nickname": "AMZ", "is_supplier": True})
    client.post("/api/location", json={"name": "Tenso/Veranda"})  # alias: VERANDA / TENSO
    client.post("/api/location", json={"name": "Chic"})
    client.post("/api/color", json={"code": "045", "name": "Rosso"})
    client.post("/api/composition", json={"code": "016", "name": "Grappolo Elio", "standard_price": "20.00"})


def _batch():
    return {
        "schema_version": 1, "kind": "orders_batch", "discount_percent": 10,
        "default_customer": "RVH",
        "orders": [
            {"location": "VERANDA", "date": "02/10/2026", "stated_total": 40,
             "items": [{"cod": 16, "name": "Grappolo Elio", "qty": 2, "line_total": 40, "colors": ["045"]}]},
            {"location": "Chic", "date": "03/10/2026",
             "items": [{"cod": 999, "name": "Boh", "qty": 1, "line_total": 50, "colors": []}]},
        ],
        "stated_gross_total": 90, "stated_net_total": 81,
    }


def _order(location="Chic", date="03/10/2026", **extra):
    return {"location": location, "date": date,
            "items": [{"cod": 16, "name": "Grappolo Elio", "qty": 1, "line_total": 20, "colors": ["045"]}],
            **extra}


def _preview(client, orders, **top):
    body = {"schema_version": 1, "kind": "orders_batch", "orders": orders, **top}
    r = client.post("/api/import/orders/preview", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_preview_resolves_alias_flags_errors_and_checksums(client):
    _seed(client)
    rep = client.post("/api/import/orders/preview", json=_batch()).json()
    assert rep["committed"] is False
    assert rep["counts"]["ok"] == 1          # VERANDA resolved via the slash-name split
    assert rep["counts"]["error"] == 1       # COD 999 unknown
    assert rep["checksum_ok"] is True        # 90 gross, 81 net
    ok = next(o for o in rep["orders"] if o["status"] == "ok")
    assert "Grappolo Elio" in ok["contents"] and "Riverside Hall" in ok["contents"]
    assert ok["computed_total"] == "36.00"   # 40 - 10%
    assert client.get("/api/order").json() == []   # preview writes nothing


def test_row_checks(client):
    _seed(client)
    rep = _preview(client, [
        {"location": "Chic", "date": "03/10/2026",       # name != COD + unknown colour
         "items": [{"cod": 16, "name": "Arco Totalmente Diverso", "qty": 1, "line_total": 20, "colors": ["999"]}]},
        {"location": "Chic", "date": "04/10/2026",       # qty 0 -> per-row error, not a 422
         "items": [{"cod": 16, "name": "Grappolo Elio", "qty": 0, "line_total": 20, "colors": ["045"]}]},
    ], default_customer="RVH")
    o0, o1 = rep["orders"]
    assert o0["status"] == "error"          # name <-> COD mismatch is unrecoverable
    msgs = " ".join(o0["messages"])
    assert "doesn't match" in msgs and "IGNORED" in msgs
    assert o1["status"] == "error"


def _seed_number(client):
    client.post("/api/party", json={"name": "Riverside Hall", "code_nickname": "RVH", "is_customer": True})
    client.post("/api/location", json={"name": "Chic"})
    client.post("/api/color", json={"code": "088", "name": "Oro"})
    client.post("/api/color", json={"code": "089", "name": "Argento"})
    num = client.post("/api/required_item", json={
        "name": "Palloncino numero 80", "unit": "piece", "used_color": True, "is_number": True}).json()
    comp = client.post("/api/composition", json={
        "code": "012", "name": "Nuvoletta con numero", "standard_price": "40.00"}).json()
    client.put(f"/api/composition/{comp['composition_id']}/bom",
               json=[{"required_item_id": num["required_item_id"], "quantity": "2"}])


def test_import_builds_numbers_with_default_colour(client):
    # Imported numbers carry their digit; omitted colour defaults to silver,
    # explicit colour is kept. Size comes from the composition BOM.
    _seed_number(client)
    body = {"schema_version": 1, "kind": "orders_batch", "default_customer": "RVH",
            "orders": [{"location": "Chic", "date": "03/10/2026", "items": [
                {"cod": 12, "name": "Nuvoletta con numero", "qty": 1, "line_total": 40,
                 "numbers": [{"digit": "3"}, {"digit": "0", "color": "088"}]}]}]}
    rep = client.post("/api/import/orders/commit", json=body).json()
    assert rep["counts"]["ok"] == 1, rep
    oid = rep["orders"][0]["created_order_id"]
    nums = client.get(f"/api/order/{oid}").json()["items"][0]["numbers"]
    colors = {c["code"]: c["color_id"] for c in client.get("/api/color").json()}
    by_digit = {n["digit"]: n["color_id"] for n in nums}
    assert by_digit == {"3": colors["089"], "0": colors["088"]}


def test_import_number_composition_without_digits_defaults_to_18(client):
    # A number composition sent without digits defaults to "18" (1 and 8) in the
    # default colour (silver here) — created cleanly as a draft, no doubt needed.
    _seed_number(client)
    body = {"schema_version": 1, "kind": "orders_batch", "default_customer": "RVH",
            "orders": [{"location": "Chic", "date": "03/10/2026", "items": [
                {"cod": 12, "name": "Nuvoletta con numero", "qty": 1, "line_total": 40}]}]}
    rep = client.post("/api/import/orders/commit", json=body).json()
    assert rep["counts"]["ok"] == 1, rep
    oid = rep["orders"][0]["created_order_id"]
    order = client.get(f"/api/order/{oid}").json()
    colors = {c["code"]: c["color_id"] for c in client.get("/api/color").json()}
    nums = order["items"][0]["numbers"]
    assert {(n["digit"], n["color_id"]) for n in nums} == {
        ("1", colors["089"]), ("8", colors["089"])}


def test_import_color_surcharge_override(client):
    # An off-catalogue colour normally adds +10%, but an explicit color_surcharges
    # entry overrides it (0 = used on the registro but not surcharged).
    client.post("/api/party", json={"name": "Riverside Hall", "code_nickname": "RVH", "is_customer": True})
    client.post("/api/location", json={"name": "Chic"})
    client.post("/api/color", json={"code": "045", "name": "Rosso"})
    client.post("/api/color", json={"code": "101", "name": "Vino", "in_catalog": False})
    client.post("/api/composition", json={"code": "002", "name": "Arco Maxi", "standard_price": "80.00"})
    body = {"schema_version": 1, "kind": "orders_batch", "default_customer": "RVH",
            "orders": [{"location": "Chic", "date": "03/10/2026", "items": [
                {"cod": 2, "name": "Arco Maxi", "qty": 1, "line_total": 80,
                 "colors": ["045", "101"], "color_surcharges": {"101": 0}}]}]}
    rep = client.post("/api/import/orders/commit", json=body).json()
    # Off-catalogue colour is flagged (doubt) but the row is still created.
    assert rep["counts"]["error"] == 0, rep
    oid = rep["orders"][0]["created_order_id"]
    assert oid is not None
    order = client.get(f"/api/order/{oid}").json()
    assert abs(float(order["total_price"]) - 80.0) < 0.005   # no +10% surcharge
    assert all(float(c["color_surcharge"] or 0) == 0 for c in order["items"][0]["colors"])


def test_customer_resolution(client):
    _seed(client)
    rep = _preview(client, [
        _order(date="01/10/2026", customer="Mario Rossi"),          # by exact name
        _order(date="02/10/2026", customer="rvh"),                  # by code, case-insensitive
        _order(date="03/10/2026"),                                  # nothing, no default
        _order(date="04/10/2026", customer="Nobody"),               # unknown
        _order(date="05/10/2026", customer="AMZ"),                  # exists but a supplier
    ])
    st = [o["status"] for o in rep["orders"]]
    assert st == ["ok", "ok", "error", "error", "error"]
    assert "Missing customer" in rep["orders"][2]["messages"][0]
    assert "Unknown customer" in rep["orders"][3]["messages"][0]
    assert "not flagged as a customer" in rep["orders"][4]["messages"][0]
    # default_customer fills the gap
    rep = _preview(client, [_order()], default_customer="RVH")
    assert rep["orders"][0]["status"] == "ok"


def test_discount_per_order_overrides_batch(client):
    _seed(client)
    rep = _preview(client, [
        _order(date="01/10/2026"),                                  # batch 10% -> 18.00
        _order(date="02/10/2026", discount_percent=0),              # own 0%  -> 20.00
        _order(date="03/10/2026", discount_percent=150),            # invalid -> error
    ], default_customer="RVH", discount_percent=10)
    totals = [o["computed_total"] for o in rep["orders"]]
    assert totals[:2] == ["18.00", "20.00"]
    assert rep["orders"][2]["status"] == "error"


def test_one_order_per_location_per_day(client):
    _seed(client)
    rep = _preview(client, [_order(), _order(items=[
        {"cod": 16, "name": "Grappolo Elio", "qty": 3, "line_total": 60, "colors": []}])],
        default_customer="RVH")
    # same location + day, DIFFERENT content: still a duplicate
    assert [o["status"] for o in rep["orders"]] == ["ok", "duplicate"]
    assert "same location and day" in rep["orders"][1]["messages"][-1]

    client.post("/api/import/orders/commit", json={
        "schema_version": 1, "kind": "orders_batch", "default_customer": "RVH",
        "orders": [_order()]})
    rep = _preview(client, [_order(items=[
        {"cod": 16, "name": "Grappolo Elio", "qty": 9, "line_total": 180, "colors": []}])],
        default_customer="RVH")
    assert rep["orders"][0]["status"] == "duplicate"
    assert "already exists" in rep["orders"][0]["messages"][-1]
    assert "draft" in rep["orders"][0]["messages"][-1]


def test_cancelled_order_does_not_block(client):
    _seed(client)
    body = {"schema_version": 1, "kind": "orders_batch", "default_customer": "RVH",
            "orders": [_order()]}
    created = client.post("/api/import/orders/commit", json=body).json()["orders"][0]["created_order_id"]
    client.patch(f"/api/order/{created}", json={"state": "cancelled"})
    assert _preview(client, [_order()], default_customer="RVH")["orders"][0]["status"] == "ok"


def test_commit_creates_drafts_and_partial_resend_works(client):
    _seed(client)
    r1 = client.post("/api/import/orders/commit", json=_batch()).json()
    assert r1["counts"]["ok"] == 1 and r1["counts"]["error"] == 1
    orders = client.get("/api/order").json()
    assert len(orders) == 1
    assert orders[0]["state"] == "draft"
    assert orders[0]["customer_party_id"] is not None
    assert "[richie]" in orders[0]["comment"]

    # fix the bad row and re-send the WHOLE file: the good one is a duplicate, the fixed one is created
    fixed = _batch()
    fixed["orders"][1]["items"][0].update({"cod": 16, "name": "Grappolo Elio", "line_total": 20})
    r2 = client.post("/api/import/orders/commit", json=fixed).json()
    assert [o["status"] for o in r2["orders"]] == ["duplicate", "ok"]
    assert len(client.get("/api/order").json()) == 2

    # and a third time nothing is created
    r3 = client.post("/api/import/orders/commit", json=fixed).json()
    assert r3["counts"]["duplicate"] == 2
    assert len(client.get("/api/order").json()) == 2


def test_off_catalogue_colour_surcharge_is_applied(client):
    _seed(client)
    # an off-catalogue colour adds 10% of the line base to the saved total
    client.post("/api/color", json={"code": "101", "name": "Bordeaux", "in_catalog": False})
    rep = client.post("/api/import/orders/commit", json={
        "schema_version": 1, "kind": "orders_batch", "default_customer": "RVH",
        "orders": [_order(discount_percent=0, items=[
            {"cod": 16, "name": "Grappolo Elio", "qty": 1, "line_total": 20, "colors": ["101"]}])]}).json()
    o = rep["orders"][0]
    assert o["status"] == "doubt" and "surcharge applied" in " ".join(o["messages"])
    assert o["computed_total"] == "22.00"            # 20 + 10% off-catalogue surcharge
    oid = o["created_order_id"]
    saved = client.get(f"/api/order/{oid}").json()
    assert float(saved["total_price"]) == 22.0       # stored total matches the app invariant
    assert "[richie]" in saved["comment"] and "dubbi:" in saved["comment"]  # doubt reason recorded


def test_line_without_cod_is_excluded_from_the_saved_total(client):
    _seed(client)
    # one good line + one line without COD: only the good one is saved and counted
    rep = client.post("/api/import/orders/commit", json={
        "schema_version": 1, "kind": "orders_batch", "default_customer": "RVH",
        "orders": [_order(discount_percent=0, items=[
            {"cod": 16, "name": "Grappolo Elio", "qty": 1, "line_total": 20, "colors": []},
            {"cod": None, "name": "Boh", "qty": 1, "line_total": 50, "colors": []}])]}).json()
    o = rep["orders"][0]
    assert o["status"] == "doubt" and o["computed_total"] == "20.00"   # the 50€ line is NOT counted
    saved = client.get(f"/api/order/{o['created_order_id']}").json()
    assert float(saved["total_price"]) == 20.0 and len(saved["items"]) == 1

    # an order whose ONLY line lacks a COD creates nothing and says so
    rep = client.post("/api/import/orders/preview", json={
        "schema_version": 1, "kind": "orders_batch", "default_customer": "RVH",
        "orders": [_order(date="09/10/2026", items=[
            {"cod": None, "name": "Boh", "qty": 1, "line_total": 50, "colors": []}])]}).json()
    assert "will not be created" in " ".join(rep["orders"][0]["messages"])


def test_line_total_not_divisible_by_qty_is_a_doubt(client):
    _seed(client)
    rep = _preview(client, [_order(discount_percent=0, items=[
        {"cod": 16, "name": "Grappolo Elio", "qty": 3, "line_total": 10, "colors": []}])],
        default_customer="RVH")
    o = rep["orders"][0]
    assert o["status"] == "doubt" and "not divisible" in " ".join(o["messages"])
    assert o["computed_total"] == "9.99"             # 3 × 3.33 (rounded unit price), not 10.00


def test_alphanumeric_composition_codes(client):
    _seed(client)
    # real catalogue codes are TEXT: colonne (05M), combos (P01), tendina (TND)
    client.post("/api/composition", json={"code": "05M", "name": "Colonne semplici 150 cm", "standard_price": "40.00"})
    client.post("/api/composition", json={"code": "P01", "name": "Combo P01", "standard_price": "110.00"})
    rep = _preview(client, [
        {"location": "Chic", "date": "03/10/2026", "discount_percent": 0,
         "items": [{"cod": "05M", "name": "Colonne semplici 150", "qty": 1, "line_total": 40, "colors": []}]},
        {"location": "Veranda", "date": "03/10/2026", "discount_percent": 0,
         "items": [{"cod": "p01", "name": "Combo", "qty": 1, "line_total": 110, "colors": []}]},   # case-insensitive
        {"location": "Chic", "date": "04/10/2026", "discount_percent": 0,
         "items": [{"cod": "16", "name": "Grappolo Elio", "qty": 1, "line_total": 20, "colors": []}]},  # numeric string -> 016
    ], default_customer="RVH")
    assert [o["status"] for o in rep["orders"]] == ["ok", "ok", "ok"]
    assert [o["computed_total"] for o in rep["orders"]] == ["40.00", "110.00", "20.00"]


# ------------------------------- expenses ----------------------------------
def _seed_exp(client):
    _seed(client)
    client.post("/api/expense_category", json={"name": "materials"})
    client.post("/api/expense_category", json={"name": "transport"})
    red = client.post("/api/color", json={"code": "046", "name": "Rosso scuro"}).json()
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()
    client.post("/api/product", json={
        "required_item_id": item["required_item_id"], "color_id": red["color_id"],
        "product_code": "RED-AMZ-G", "name": "Gemar 30cm Rosso", "package_quantity": 100})


def _exp_body(**extra):
    exp = {"date": "04/09/2026", "paid_to": "AMZ", "payment_method": "card",
           "items": [{"product_code": "RED-AMZ-G", "qty": 2, "line_total": 24},
                     {"description": "Shipping", "qty": 1, "line_total": 12, "category": "transport"}]}
    exp.update(extra)
    return {"schema_version": 1, "kind": "expenses_batch", "default_paid_by": "RVH",
            "expenses": [exp], "stated_total": 36}


def test_expense_preview_and_commit_with_stock_refill(client):
    _seed_exp(client)
    rep = client.post("/api/import/expenses/preview", json=_exp_body()).json()
    assert rep["counts"]["ok"] == 1 and rep["checksum_ok"] is True
    assert rep["orders"][0]["computed_total"] == "36.00"
    assert client.get("/api/expense").json() == []

    rep = client.post("/api/import/expenses/commit", json=_exp_body()).json()
    exp_id = rep["orders"][0]["created_expense_id"]
    assert exp_id
    exp = client.get(f"/api/expense/{exp_id}").json()
    assert float(exp["total_cost"]) == 36.0 and len(exp["items"]) == 2
    assert "[richie]" in exp["comment"]
    # 2 packs x 100 pieces of the known product raised stock
    assert sum(r["quantity"] for r in client.get("/api/stock").json()) == 200


def test_expense_duplicates_and_resend(client):
    _seed_exp(client)
    client.post("/api/import/expenses/commit", json=_exp_body())
    rep = client.post("/api/import/expenses/commit", json=_exp_body()).json()
    assert rep["counts"]["duplicate"] == 1
    assert len(client.get("/api/expense").json()) == 1
    # same row twice inside one file
    body = _exp_body(date="05/09/2026")
    body["expenses"].append(body["expenses"][0])
    rep = client.post("/api/import/expenses/preview", json=body).json()
    assert [o["status"] for o in rep["orders"]] == ["ok", "duplicate"]


def test_expense_checks(client):
    _seed_exp(client)
    body = _exp_body()
    good = body["expenses"][0]
    body["expenses"] = [
        {**good, "paid_to": "Nobody"},                                              # unknown payee
        {**good, "paid_by": "AMZ"},                                                 # payer == payee
        {**good, "date": "xx"},                                                     # bad date
        {**good, "items": []},                                                      # no lines
        {**good, "items": [{"description": "x", "qty": 1, "line_total": 5}]},       # no category
        {**good, "items": [{"description": "x", "qty": 1, "line_total": 5, "category": "nope"}]},
        {**good, "items": [{"product_code": "???", "qty": 1, "line_total": 5}]},    # unknown product -> doubt
        {**good, "paid_to": "Mario Rossi"},                                         # not a supplier -> doubt
        {**good, "stated_total": 99},                                               # total mismatch -> doubt
    ]
    rep = client.post("/api/import/expenses/preview", json=body).json()
    assert [o["status"] for o in rep["orders"]] == [
        "error", "error", "error", "error", "error", "error", "doubt", "doubt", "doubt"]
    assert "WITHOUT product" in rep["orders"][6]["messages"][0]


def test_prompt_is_built_from_spec_and_master_data(client):
    _seed_exp(client)
    p = client.get("/api/import/prompt/orders").json()["prompt"]
    assert "orders_batch" in p and "O23" in p and "Chic" in p and "RVH = Riverside Hall" in p
    assert "expenses_batch" not in p.split("# MASTER DATA")[0]
    p = client.get("/api/import/prompt/expenses").json()["prompt"]
    assert "expenses_batch" in p and "RED-AMZ-G" in p and "transport" in p
    assert client.get("/api/import/prompt/nope").status_code == 404


# ------------------------------- stock -------------------------------------
def _seed_stock(client):
    color = client.post("/api/color", json={"code": "045", "name": "Rosso"}).json()
    item = client.post("/api/required_item", json={
        "name": "Palloncino grande", "unit": "piece", "used_color": True}).json()
    client.post("/api/required_item", json={"name": "Nastro", "unit": "piece"})
    return color, item


def _red_line(qty, name="Rosso"):
    return {"item": "Palloncino grande", "color_code": "045", "color_name": name, "quantity": qty}


def test_stock_gift_recount_and_idempotency(client):
    _seed_stock(client)
    gift = {"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "gift", "date": "02/10/2026", "items": [_red_line(20)]}]}
    rep = client.post("/api/import/stock/commit", json=gift).json()
    assert rep["counts"]["ok"] == 1 and rep["orders"][0]["created_id"]
    assert sum(r["quantity"] for r in client.get("/api/stock").json()) == 20

    # re-sending the same gift -> duplicate line, not created again
    rep = client.post("/api/import/stock/commit", json=gift).json()
    assert rep["orders"][0]["status"] == "duplicate"
    assert sum(r["quantity"] for r in client.get("/api/stock").json()) == 20

    # recount to 30 -> the checkpoint sets the absolute to 30
    rec = {"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "recount", "date": "03/10/2026", "items": [_red_line(30)]}]}
    rep = client.post("/api/import/stock/commit", json=rec).json()
    assert rep["orders"][0]["created_id"]
    assert sum(r["quantity"] for r in client.get("/api/stock").json()) == 30

    # re-sending the SAME recount (same date+value) -> duplicate, nothing added
    rep = client.post("/api/import/stock/commit", json=rec).json()
    assert rep["orders"][0]["status"] == "duplicate"
    assert sum(r["quantity"] for r in client.get("/api/stock").json()) == 30


def test_recount_is_an_absolute_checkpoint(client):
    """A recount fixes the quantity at its date: anything dated before it — even
    added later — must not change today's stock; only later movements count."""
    _seed_stock(client)
    def commit(type_, date, qty):
        return client.post("/api/import/stock/commit", json={
            "schema_version": 1, "kind": "stock_batch",
            "updates": [{"type": type_, "date": date, "items": [_red_line(qty)]}]}).json()
    total = lambda: sum(r["quantity"] for r in client.get("/api/stock").json())

    commit("gift", "05/10/2026", 100)          # +100 on day 5
    commit("recount", "10/10/2026", 80)        # counted 80 on day 10 -> stock 80
    assert total() == 80
    commit("gift", "01/10/2026", 50)           # BACK-DATED before the recount
    assert total() == 80                        # recount is law: unaffected
    commit("gift", "11/10/2026", 5)            # after the recount -> adds
    assert total() == 85


def test_stock_recount_zero_empties(client):
    _seed_stock(client)
    client.post("/api/import/stock/commit", json={"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "gift", "date": "02/10/2026", "items": [_red_line(20)]}]})
    rep = client.post("/api/import/stock/commit", json={"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "recount", "date": "03/10/2026", "items": [_red_line(0)]}]}).json()
    assert rep["orders"][0]["created_id"]  # recount to 0 is allowed and applied
    assert sum(r["quantity"] for r in client.get("/api/stock").json()) == 0


def test_stock_colour_code_name_must_match(client):
    _seed_stock(client)
    body = {"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "gift", "date": "02/10/2026", "items": [_red_line(10, name="Blu")]}]}
    rep = client.post("/api/import/stock/preview", json=body).json()
    assert rep["orders"][0]["status"] == "error"
    assert "not 'Blu'" in " ".join(rep["orders"][0]["messages"])


def test_stock_one_recount_per_cell(client):
    _seed_stock(client)
    body = {"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "recount", "date": "02/10/2026", "items": [_red_line(10), _red_line(15)]}]}
    rep = client.post("/api/import/stock/preview", json=body).json()
    assert "ambiguous" in " ".join(rep["orders"][0]["messages"])


def test_stock_partial_commit_and_reupload(client):
    _seed_stock(client)
    # one update: a bad line (wrong colour name) + a good line -> good is kept
    bad = {"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "gift", "date": "02/10/2026",
         "items": [_red_line(10, name="WRONG"), {"item": "Nastro", "quantity": 7}]}]}
    rep = client.post("/api/import/stock/commit", json=bad).json()
    assert rep["orders"][0]["status"] == "doubt" and rep["orders"][0]["created_id"]
    stock = {(r["required_item_name"], r["color_name"]): r["quantity"] for r in client.get("/api/stock").json()}
    assert stock[("Nastro", None)] == 7
    assert ("Palloncino grande", "Rosso") not in stock  # bad line NOT created

    # fix the colour name, re-send: red added, Nastro recognised as duplicate (not doubled)
    fixed = {"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "gift", "date": "02/10/2026",
         "items": [_red_line(10), {"item": "Nastro", "quantity": 7}]}]}
    rep = client.post("/api/import/stock/commit", json=fixed).json()
    assert rep["orders"][0]["status"] == "doubt" and rep["orders"][0]["created_id"]
    stock = {(r["required_item_name"], r["color_name"]): r["quantity"] for r in client.get("/api/stock").json()}
    assert stock[("Palloncino grande", "Rosso")] == 10
    assert stock[("Nastro", None)] == 7  # not doubled


def test_stock_checks(client):
    _seed_stock(client)
    body = {"schema_version": 1, "kind": "stock_batch", "updates": [
        {"type": "nope", "date": "02/10/2026",
         "items": [{"item": "Nastro", "quantity": 5}]},                               # bad type
        {"type": "loss", "date": "02/10/2026",
         "items": [{"item": "Sconosciuto", "quantity": 5}]},                          # unknown material
        {"type": "loss", "date": "02/10/2026",
         "items": [{"item": "Palloncino grande", "quantity": 5}]},                    # coloured, no colour -> error
    ]}
    rep = client.post("/api/import/stock/preview", json=body).json()
    assert [o["status"] for o in rep["orders"]] == ["error", "error", "error"]
    assert "coloured" in " ".join(rep["orders"][2]["messages"])


def test_expense_cost_differs_from_product_default(client):
    _seed_exp(client)
    pid = next(p["product_id"] for p in client.get("/api/product").json()
               if p["product_code"] == "RED-AMZ-G")
    client.patch(f"/api/product/{pid}", json={"default_price": "12.00"})

    # 2 packs for 24 -> unit 12 == default: no cost doubt
    rep = client.post("/api/import/expenses/preview", json=_exp_body()).json()
    assert "cost:" not in " ".join(rep["orders"][0]["messages"])

    # 2 packs for 30 -> unit 15 != default 12: doubt
    body = _exp_body()
    body["expenses"][0]["items"][0]["line_total"] = 30
    body["expenses"][0]["stated_total"] = 42          # 30 + 12 shipping, avoid total-mismatch noise
    body["stated_total"] = 42
    rep = client.post("/api/import/expenses/preview", json=body).json()
    o = rep["orders"][0]
    assert o["status"] == "doubt" and "usual 12.00" in " ".join(o["messages"])


# -------------------------------- work -------------------------------------
def _seed_work(client):
    client.post("/api/party", json={"name": "Alice", "code_nickname": "AL", "is_worker": True})
    client.post("/api/party", json={"name": "Mario Rossi", "is_customer": True})


def test_work_create_and_checks(client):
    _seed_work(client)
    body = {"schema_version": 1, "kind": "work_batch", "default_date": "02/10/2026", "entries": [
        {"worker": "AL", "start": "09:00", "end": "17:30", "break_minutes": 30, "tasks": "archi"},
        {"worker": "Mario Rossi", "start": "09:00", "end": "12:00"},        # not a worker -> error
        {"worker": "Nobody", "start": "09:00", "end": "12:00"},             # unknown -> error
        {"worker": "AL", "date": "03/10/2026", "start": "17:00", "end": "09:00"},  # end<start -> error
    ]}
    rep = client.post("/api/import/work/commit", json=body).json()
    assert [o["status"] for o in rep["orders"]] == ["ok", "error", "error", "error"]
    work = client.get("/api/work").json()
    assert len(work) == 1 and "[richie]" in work[0]["comment"]

    # re-send the good one -> duplicate
    again = {"schema_version": 1, "kind": "work_batch", "default_date": "02/10/2026", "entries": [
        {"worker": "AL", "start": "09:00", "end": "17:30", "break_minutes": 30, "tasks": "archi"}]}
    rep = client.post("/api/import/work/commit", json=again).json()
    assert rep["counts"]["duplicate"] == 1 and len(client.get("/api/work").json()) == 1


# ------------------------------ transfers ----------------------------------
def test_transfers_create_checks_and_duplicates(client):
    client.post("/api/party", json={"name": "Riverside Hall", "code_nickname": "RVH", "is_customer": True})
    client.post("/api/party", json={"name": "Alice", "code_nickname": "AL", "is_worker": True})
    body = {"schema_version": 1, "kind": "transfers_batch", "default_from": "RVH",
            "transfers": [
                {"to_party": "AL", "date": "02/10/2026", "amount": 150},
                {"from_party": "RVH", "to_party": "RVH", "date": "02/10/2026", "amount": 10},  # same party
                {"to_party": "AL", "date": "02/10/2026", "amount": 0},                        # bad amount
            ], "stated_total": 150}
    rep = client.post("/api/import/transfers/commit", json=body).json()
    assert [o["status"] for o in rep["orders"]] == ["ok", "error", "error"]
    assert rep["checksum_ok"] is True
    assert len(client.get("/api/money_transfer").json()) == 1

    # re-send -> duplicate
    rep = client.post("/api/import/transfers/commit", json=body).json()
    assert rep["counts"]["duplicate"] == 1
    assert len(client.get("/api/money_transfer").json()) == 1


def test_new_kind_prompts(client):
    _seed_stock(client)
    _seed_work(client)
    assert "stock_batch" in client.get("/api/import/prompt/stock").json()["prompt"]
    assert "work_batch" in client.get("/api/import/prompt/work").json()["prompt"]
    assert "transfers_batch" in client.get("/api/import/prompt/transfers").json()["prompt"]
