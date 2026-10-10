"""Relationship & constraint tests for the v2 schema."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Color,
    Composition,
    CustomerOrder,
    Expense,
    ExpenseCategory,
    ExpenseItem,
    InventoryUpdate,
    InventoryUpdateItem,
    Location,
    OrderItem,
    OrderItemColor,
    Party,
    Product,
    RequiredItem,
    Requirement,
)


def _order_with_colors(db):
    """One order -> one item -> two colors, returns (order, red, white)."""
    location = Location(name="CHIC")
    comp = Composition(code="001", name="Arco", standard_price=Decimal("100.00"))
    red = Color(code="045", name="Rosso")
    white = Color(code="001", name="Bianco")
    db.add_all([location, comp, red, white])
    db.flush()

    order = CustomerOrder(location=location, state="confirmed", date=date(2026, 1, 1),
                          total_price=Decimal("100.00"))
    item = OrderItem(order=order, composition=comp, quantity=2, unit_price=Decimal("50.00"))
    item.colors = [
        OrderItemColor(color=red, color_percentage=Decimal("70.00")),
        OrderItemColor(color=white, color_percentage=Decimal("30.00")),
    ]
    db.add(order)
    db.commit()
    return order, red, white


def test_order_round_trip_and_snapshot(db_session):
    order, red, white = _order_with_colors(db_session)
    db_session.refresh(order)
    item = order.items[0]
    # Historical snapshot is independent from current master price.
    assert item.unit_price == Decimal("50.00")
    assert item.composition.standard_price == Decimal("100.00")
    assert {c.color.code: c.color_percentage for c in item.colors} == {
        "045": Decimal("70.00"), "001": Decimal("30.00")}


def test_order_item_color_unique(db_session):
    order, red, _ = _order_with_colors(db_session)
    db_session.add(OrderItemColor(order_item=order.items[0], color=red,
                                  color_percentage=Decimal("10.00")))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_quantity_must_be_positive(db_session):
    location = Location(name="L")
    comp = Composition(code="X", name="X", standard_price=Decimal("1.00"))
    db_session.add_all([location, comp])
    db_session.flush()
    order = CustomerOrder(location=location, state="draft", date=date(2026, 1, 1),
                          total_price=Decimal("0.00"))
    OrderItem(order=order, composition=comp, quantity=0, unit_price=Decimal("1.00"))
    db_session.add(order)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_party_requires_a_role(db_session):
    """A party with no role flag violates the at_least_one_role CHECK."""
    db_session.add(Party(name="Nessun ruolo"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_order_state_must_be_valid(db_session):
    location = Location(name="L")
    db_session.add(location)
    db_session.flush()
    db_session.add(CustomerOrder(location=location, state="bogus", date=date(2026, 1, 1),
                                 total_price=Decimal("0.00")))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_expense_payer_differs_from_payee(db_session):
    biz = Party(name="AI.R", is_supplier=True)
    db_session.add(biz)
    db_session.flush()
    db_session.add(Expense(paid_by=biz, paid_to=biz, date=date(2026, 1, 1),
                           total_cost=Decimal("10.00")))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_expense_with_items(db_session):
    biz = Party(name="AI.R", is_customer=True)
    supplier = Party(name="Amazon", is_supplier=True)
    cat = ExpenseCategory(name="materials")
    item = RequiredItem(name="Palloncino grande", unit="piece", used_color=True)
    db_session.add_all([biz, supplier, cat, item])
    db_session.flush()
    product = Product(required_item=item, name="Palloncino rosso")
    db_session.add(product)
    db_session.flush()

    expense = Expense(paid_by=biz, paid_to=supplier, date=date(2026, 1, 1),
                      total_cost=Decimal("60.00"))
    expense.items = [ExpenseItem(product=product, category=cat, quantity=10,
                                 unit_cost=Decimal("6.00"))]
    db_session.add(expense)
    db_session.commit()
    db_session.refresh(expense)
    assert expense.items[0].unit_cost == Decimal("6.00")
    assert expense.paid_to.name == "Amazon"


def test_bom_requirements(db_session):
    """A composition needs quantities of required_items."""
    comp = Composition(code="001", name="Arco", standard_price=Decimal("100.00"))
    big = RequiredItem(name="Palloncino grande", unit="piece", used_color=True)
    small = RequiredItem(name="Palloncino piccolo", unit="piece", used_color=True)
    db_session.add_all([comp, big, small])
    db_session.flush()
    db_session.add_all([
        Requirement(composition=comp, required_item=big, quantity=Decimal("40")),
        Requirement(composition=comp, required_item=small, quantity=Decimal("120")),
    ])
    db_session.commit()
    db_session.refresh(comp)
    needs = {r.required_item.name: r.quantity for r in comp.requirements}
    assert needs["Palloncino grande"] == Decimal("40.00")


def test_stock_derived_at_required_item_level(db_session):
    """Stock is SUM(quantity_change) grouped by required_item, not per product."""
    item = RequiredItem(name="Palloncino grande", unit="piece")
    db_session.add(item)
    db_session.flush()
    upd = InventoryUpdate(type="purchase", date=date(2026, 1, 1))
    upd.items = [InventoryUpdateItem(required_item=item, quantity_change=500)]
    db_session.add(upd)
    usage = InventoryUpdate(type="order_usage", date=date(2026, 1, 5))
    usage.items = [InventoryUpdateItem(required_item=item, quantity_change=-80)]
    db_session.add(usage)
    db_session.commit()

    stock = db_session.query(func.sum(InventoryUpdateItem.quantity_change)).filter(
        InventoryUpdateItem.required_item_id == item.required_item_id).scalar()
    assert stock == 420