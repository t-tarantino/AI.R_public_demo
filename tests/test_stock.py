"""Stock derivation & reorder-threshold behaviour."""
from __future__ import annotations

from app.api.stock import compute_stock
from app.db.models import Color, RequiredItem, StockThreshold


def _balloon(db) -> RequiredItem:
    item = RequiredItem(name="Palloncino grande", unit="piece", used_color=True,
                        minimum_safe_quantity=100)
    db.add(item)
    db.flush()
    return item


def test_threshold_on_empty_cell_still_warns(db_session):
    """A per-colour minimum must raise a below-minimum row even when that colour
    has no stock movements yet (regression: such cells used to produce no row,
    so editing their threshold had no visible effect)."""
    item = _balloon(db_session)
    red = Color(code="045", name="Rosso")
    db_session.add(red)
    db_session.flush()
    db_session.add(StockThreshold(required_item_id=item.required_item_id,
                                  color_id=red.color_id, minimum_quantity=50))
    db_session.commit()

    rows = compute_stock(db_session)
    red_row = next(r for r in rows if r.color_id == red.color_id)
    assert red_row.quantity == 0
    assert red_row.effective_minimum == 50
    assert red_row.below_minimum is True


def test_blanket_threshold_makes_no_phantom_cell(db_session):
    """A threshold with no colour AND no digit is a blanket minimum, not a real
    cell, so it must not materialise a bogus (colour=None, digit=None) row."""
    item = _balloon(db_session)
    db_session.add(StockThreshold(required_item_id=item.required_item_id,
                                  color_id=None, variant=None, minimum_quantity=80))
    db_session.commit()

    rows = compute_stock(db_session)
    assert rows == []


def test_color_threshold_overrides_item_default(db_session):
    """The most specific matching threshold wins over the item default."""
    item = _balloon(db_session)  # default minimum 100
    blue = Color(code="010", name="Blu")
    db_session.add(blue)
    db_session.flush()
    db_session.add(StockThreshold(required_item_id=item.required_item_id,
                                  color_id=blue.color_id, minimum_quantity=250))
    db_session.commit()

    rows = compute_stock(db_session)
    blue_row = next(r for r in rows if r.color_id == blue.color_id)
    assert blue_row.effective_minimum == 250  # colour threshold, not the 100 default


def _make_material_and_color(client) -> tuple[int, int, int]:
    ri = client.post("/api/required_item",
                     json={"name": "Palloncino grande", "unit": "piece", "used_color": True})
    assert ri.status_code == 201, ri.text
    c1 = client.post("/api/color", json={"code": "001", "name": "Bianco"})
    c2 = client.post("/api/color", json={"code": "014", "name": "Nero"})
    return ri.json()["required_item_id"], c1.json()["color_id"], c2.json()["color_id"]


def test_duplicate_threshold_rejected(client):
    """A second threshold for the same material+colour (digit NULL) must 400 — the
    DB UNIQUE constraint misses it because SQL treats NULL digits as distinct."""
    ri_id, white, black = _make_material_and_color(client)
    first = client.post("/api/stock_threshold",
                        json={"required_item_id": ri_id, "color_id": white, "minimum_quantity": 200})
    assert first.status_code == 201, first.text

    dup = client.post("/api/stock_threshold",
                      json={"required_item_id": ri_id, "color_id": white, "minimum_quantity": 150})
    assert dup.status_code == 400
    assert "already exists" in dup.json()["detail"]

    # A different colour on the same material is fine.
    other = client.post("/api/stock_threshold",
                        json={"required_item_id": ri_id, "color_id": black, "minimum_quantity": 150})
    assert other.status_code == 201, other.text


def test_patch_into_duplicate_rejected(client):
    """Editing a threshold so it collides with another must also 400."""
    ri_id, white, black = _make_material_and_color(client)
    client.post("/api/stock_threshold",
                json={"required_item_id": ri_id, "color_id": white, "minimum_quantity": 200})
    black_row = client.post("/api/stock_threshold",
                            json={"required_item_id": ri_id, "color_id": black, "minimum_quantity": 150})
    tid = black_row.json()["stock_threshold_id"]

    # Re-point the black threshold onto white -> collision.
    clash = client.patch(f"/api/stock_threshold/{tid}", json={"color_id": white})
    assert clash.status_code == 400
    assert "already exists" in clash.json()["detail"]

    # Editing only its own minimum stays allowed (not a self-collision).
    ok = client.patch(f"/api/stock_threshold/{tid}", json={"minimum_quantity": 99})
    assert ok.status_code == 200, ok.text
