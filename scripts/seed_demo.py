"""Populate the database with FAKE transactional history for the demo.

Generates a believable four-month history (September–December 2026) of orders,
expenses, money transfers, work sessions AND the stock movements they imply
(opening recount, purchases/refills, order consumption, plus a couple of manual
corrections), so the public demo shows a lived-in dataset rather than empty
screens.

    python -m scripts.import_data   # master data first (from the example seed)
    python -m scripts.create_users  # demo accounts
    python -m scripts.seed_demo     # <- this: fake operational history

Idempotent: it wipes existing transactional + inventory rows and rebuilds them.
Master data, user accounts and the audit log are left untouched. All
amounts/dates are invented — there is no real business data here.
"""
from __future__ import annotations

import calendar
import random
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import delete

from app.db.models import (
    Color,
    Composition,
    CustomerOrder,
    Expense,
    ExpenseItem,
    ExpenseCategory,
    InventoryUpdate,
    InventoryUpdateItem,
    Location,
    MoneyTransfer,
    OrderItem,
    OrderItemColor,
    OrderItemNumber,
    Party,
    Product,
    RequiredItem,
    Work,
)
from app.db.models.work import work_order
from app.services.consumption import build_consumption
from app.services.refill import build_refill
from app.db.session import SessionLocal

MONTHS = [(2026, 9), (2026, 10), (2026, 11), (2026, 12)]
CENTS = Decimal("0.01")
EVENTS = ["birthday", "wedding", "anniversary", "corporate", "baby shower", "graduation"]
TASKS = ["Setup arches and columns", "Helium fills + delivery", "On-site assembly",
         "Teardown and cleanup", "Backdrop + ceiling installation"]


def _q(x) -> Decimal:
    return Decimal(x).quantize(CENTS, rounding=ROUND_HALF_UP)


def _wipe(db) -> None:
    """Remove transactional + inventory rows only (keep master data, users, audit)."""
    db.execute(delete(work_order))
    # Inventory first: its lines reference expense_item / customer_order.
    for model in (InventoryUpdateItem, InventoryUpdate, Work, ExpenseItem, Expense,
                  MoneyTransfer, OrderItemColor, OrderItemNumber, OrderItem, CustomerOrder):
        db.query(model).delete(synchronize_session=False)
    db.flush()


def _dates_in_month(year: int, month: int, n: int, rng: random.Random) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    days = sorted(rng.sample(range(1, last + 1), min(n, last)))
    return [date(year, month, d) for d in days]


def seed() -> None:
    rng = random.Random(42)
    db = SessionLocal()
    try:
        _wipe(db)

        business = db.query(Party).filter(Party.is_business.is_(True)).one()
        customer = db.query(Party).filter(Party.code_nickname == "RVH").one()
        workers = db.query(Party).filter(Party.is_worker.is_(True)).order_by(Party.party_id).all()
        suppliers = db.query(Party).filter(Party.is_supplier.is_(True)).all()
        locations = db.query(Location).filter(Location.name != "To be defined").all()
        comps = db.query(Composition).all()
        colors = {c.code: c for c in db.query(Color).all()}
        in_cat_colors = [c for c in colors.values() if c.in_catalog]
        off_cat = next((c for c in colors.values() if not c.in_catalog), None)
        materials_cat = (db.query(ExpenseCategory).filter(ExpenseCategory.name == "materials").one())
        transport_cat = (db.query(ExpenseCategory)
                         .filter(ExpenseCategory.name == "transport").first() or materials_cat)
        products = db.query(Product).all()
        items_by_name = {ri.name: ri for ri in db.query(RequiredItem).all()}
        large = items_by_name.get("Palloncino grande")
        small = items_by_name.get("Palloncino piccolo")
        longb = items_by_name.get("Palloncino lungo")
        helium = items_by_name.get("Elio")
        foil = items_by_name.get("Palloncino numero 80")
        silver = colors.get("089")
        gold = colors.get("088")

        n_orders = n_exp = n_tx = n_work = n_inv = 0

        # --- Opening stock count (recount = absolute checkpoint) at Sep 1 -----
        opening = InventoryUpdate(type="recount", date=date(2026, 9, 1),
                                  comment="Opening stock count")
        for ri, base in ((large, 500), (small, 700)):
            if ri is None:
                continue
            for c in in_cat_colors + ([off_cat] if off_cat else []):
                opening.items.append(InventoryUpdateItem(
                    required_item_id=ri.required_item_id, color_id=c.color_id,
                    quantity_change=base))
        # Colourless materials (long balloons, helium) — a single stock figure.
        for ri, base in ((longb, 400), (helium, 1200)):
            if ri is None:
                continue
            opening.items.append(InventoryUpdateItem(
                required_item_id=ri.required_item_id, color_id=None,
                quantity_change=base))
        # Foil numbers, per digit, in silver and gold (the regularly-stocked ones).
        if foil:
            for col in (c for c in (silver, gold) if c):
                for d in "0123456789":
                    opening.items.append(InventoryUpdateItem(
                        required_item_id=foil.required_item_id, color_id=col.color_id,
                        variant=d, quantity_change=20))
        db.add(opening)
        db.flush()
        n_inv += 1

        for (year, month) in MONTHS:
            order_dates = _dates_in_month(year, month, rng.randint(7, 10), rng)
            month_orders: list[CustomerOrder] = []

            # --- Orders (completed), each with 1–3 composition lines ---------
            for d in order_dates:
                order = CustomerOrder(
                    location_id=rng.choice(locations).location_id,
                    customer_party_id=customer.party_id,
                    state="completed",
                    event_type=rng.choice(EVENTS),
                    date=d,
                    total_price=Decimal("0"),
                )
                db.add(order)
                db.flush()
                total = Decimal("0")
                for _ in range(rng.randint(1, 3)):
                    comp = rng.choice(comps)
                    qty = rng.randint(1, 4)
                    unit = Decimal(comp.standard_price)
                    discount = Decimal("10") if rng.random() < 0.8 else Decimal("0")
                    item = OrderItem(customer_order_id=order.customer_order_id,
                                     composition_id=comp.composition_id, quantity=qty,
                                     unit_price=unit, discount=discount)
                    db.add(item)
                    db.flush()
                    line = unit * qty * (Decimal("100") - discount) / Decimal("100")
                    chosen = rng.sample(in_cat_colors, rng.randint(1, 2))
                    for c in chosen:
                        db.add(OrderItemColor(order_item_id=item.order_item_id,
                                              color_id=c.color_id, color_surcharge=Decimal("0")))
                    if off_cat and rng.random() < 0.25:
                        surcharge = _q(unit * qty * Decimal("0.10"))
                        db.add(OrderItemColor(order_item_id=item.order_item_id,
                                              color_id=off_cat.color_id, color_surcharge=surcharge))
                        line += surcharge
                    # Foil-number compositions record their digits so completing
                    # the order consumes them (build_consumption reads item.numbers).
                    num_reqs = [r for r in comp.requirements if r.required_item.is_number]
                    num_color = silver or gold
                    if num_reqs and num_color is not None:
                        for req in num_reqs:
                            for digit in ("1", "8"):
                                db.add(OrderItemNumber(
                                    order_item_id=item.order_item_id,
                                    required_item_id=req.required_item_id,
                                    color_id=num_color.color_id, digit=digit, quantity=qty))
                    total += line
                order.total_price = _q(total)
                db.flush()
                # Theoretical stock consumption from the BOM (order_usage movement).
                consumption = build_consumption(db, order)
                if consumption is not None:
                    db.add(consumption)
                    n_inv += 1
                month_orders.append(order)
                n_orders += 1

            # --- Expenses: the business buys materials (-> stock refill) -----
            for d in _dates_in_month(year, month, rng.randint(2, 4), rng):
                supplier = rng.choice(suppliers)
                exp = Expense(paid_by_party_id=business.party_id,
                              paid_to_party_id=supplier.party_id, date=d,
                              payment_method=rng.choice(["card", "transfer", "cash"]),
                              total_cost=Decimal("0"))
                db.add(exp)
                db.flush()
                subtotal = Decimal("0")
                for _ in range(rng.randint(1, 3)):
                    prod = rng.choice(products) if products and rng.random() < 0.85 else None
                    qty = rng.randint(1, 6)
                    unit_cost = _q(Decimal(rng.randint(8, 40)) + Decimal("0.90"))
                    db.add(ExpenseItem(
                        expense_id=exp.expense_id,
                        product_id=prod.product_id if prod else None,
                        expense_category_id=materials_cat.expense_category_id,
                        description=None if prod else "Assorted supplies",
                        quantity=qty, unit_cost=unit_cost))
                    subtotal += unit_cost * qty
                exp.total_cost = _q(subtotal)
                db.flush()
                # Product lines raise stock (purchase movement).
                refill = build_refill(db, exp)
                if refill is not None:
                    db.add(refill)
                    n_inv += 1
                n_exp += 1

            # A monthly fuel/transport expense, paid by the business.
            fuel = Expense(paid_by_party_id=business.party_id,
                           paid_to_party_id=rng.choice(suppliers).party_id,
                           date=date(year, month, rng.randint(1, 28)),
                           payment_method="card", total_cost=Decimal("0"))
            db.add(fuel)
            db.flush()
            fuel_cost = _q(Decimal(rng.randint(30, 70)))
            db.add(ExpenseItem(expense_id=fuel.expense_id,
                               expense_category_id=transport_cat.expense_category_id,
                               description="Van fuel for deliveries", quantity=1,
                               unit_cost=fuel_cost))
            fuel.total_cost = fuel_cost
            n_exp += 1

            # --- Money transfers: customer pays the business for the month ---
            month_revenue = sum((o.total_price for o in month_orders), Decimal("0"))
            if month_revenue > 0:
                db.add(MoneyTransfer(
                    from_party_id=customer.party_id, to_party_id=business.party_id,
                    date=date(year, month, min(28, calendar.monthrange(year, month)[1])),
                    amount=_q(month_revenue * Decimal("0.9")), payment_method="transfer",
                    comment="Monthly settlement for completed orders"))
                n_tx += 1

            # --- Work sessions: each worker a few shifts, linked to orders ---
            for w in workers:
                for d in _dates_in_month(year, month, rng.randint(2, 4), rng):
                    start = datetime(d.year, d.month, d.day, rng.choice([8, 9, 14]), 0)
                    end = start + timedelta(hours=rng.randint(3, 7))
                    ws = Work(party_id=w.party_id, start_at=start, end_at=end,
                              break_minutes=rng.choice([0, 15, 30]),
                              tasks_accomplished=rng.choice(TASKS))
                    if month_orders and rng.random() < 0.7:
                        ws.orders.append(rng.choice(month_orders))
                    db.add(ws)
                    n_work += 1

        # --- A few manual stock movements (loss / gift / corrective recount) -
        if large and small:
            loss = InventoryUpdate(type="loss", date=date(2026, 10, 12),
                                   comment="Breakage during transport")
            loss.items.append(InventoryUpdateItem(
                required_item_id=large.required_item_id, color_id=colors["010"].color_id,
                quantity_change=-25))
            db.add(loss)
            n_inv += 1

            gift = InventoryUpdate(type="gift", date=date(2026, 11, 8),
                                   comment="Donated to a local school event")
            gift.items.append(InventoryUpdateItem(
                required_item_id=small.required_item_id, color_id=colors["028"].color_id,
                quantity_change=-40))
            db.add(gift)
            n_inv += 1

            # Year-end physical recount: fixes today's ABSOLUTE stock, so the demo
            # shows realistic figures (<= 500) regardless of prior movements — with a
            # few empty and a few below-threshold cells to light up the warnings.
            final = InventoryUpdate(type="recount", date=date(2026, 12, 31),
                                    comment="Year-end physical count")
            recount_colors = in_cat_colors + ([off_cat] if off_cat else [])
            for i, c in enumerate(recount_colors):
                qv = 120 + (i * 31) % 360          # 120..479, comfortably stocked
                if c.code == "010":
                    qv = 30            # below threshold (80) -> warning
                elif c.code == "045":
                    qv = 0             # empty shelf
                elif c.code == "002":
                    qv = 12            # very low
                elif not c.in_catalog:
                    qv = 110           # off-catalogue colours kept modest
                final.items.append(InventoryUpdateItem(
                    required_item_id=large.required_item_id, color_id=c.color_id,
                    quantity_change=qv))
            for i, c in enumerate(recount_colors):
                qv = 220 + (i * 29) % 260          # 220..479, above the 200 default min
                if c.code == "028":
                    qv = 120           # below threshold (150) -> warning
                elif c.code == "013":
                    qv = 0             # empty shelf
                elif not c.in_catalog:
                    qv = 210
                final.items.append(InventoryUpdateItem(
                    required_item_id=small.required_item_id, color_id=c.color_id,
                    quantity_change=qv))
            if longb:
                final.items.append(InventoryUpdateItem(
                    required_item_id=longb.required_item_id, color_id=None, quantity_change=60))
            if helium:
                final.items.append(InventoryUpdateItem(
                    required_item_id=helium.required_item_id, color_id=None, quantity_change=300))
            if foil:
                for col in (c for c in (silver, gold) if c):
                    final.items.append(InventoryUpdateItem(required_item_id=foil.required_item_id, color_id=col.color_id, variant=None, quantity_change=25))
                    for d in "0123456789":
                        qv = 12 + (int(d) * 4) % 24
                        if col is silver and d == "8":
                            qv = 2     # below threshold (5)
                        if col is gold and d in ("4", "7"):
                            qv = 0
                        final.items.append(InventoryUpdateItem(
                            required_item_id=foil.required_item_id, color_id=col.color_id,
                            variant=d, quantity_change=qv))
            db.add(final)
            n_inv += 1

            # Confirmed (not yet completed) FUTURE orders drive the forward-looking
            # shortage forecast (red/orange/yellow) against the low/empty cells.
            arch = next((c for c in comps if c.code == "001"), comps[0])
            cloud = next((c for c in comps if c.code == "003"), comps[0])
            for i, fd in enumerate((date(2026, 10, 15), date(2026, 10, 18),
                                    date(2026, 11, 20), date(2026, 12, 6))):
                comp = arch if i % 2 == 0 else cloud
                low = colors["010"] if comp is arch else colors["028"]
                o = CustomerOrder(location_id=rng.choice(locations).location_id,
                                  customer_party_id=customer.party_id, state="confirmed",
                                  event_type=rng.choice(EVENTS), date=fd,
                                  total_price=Decimal("0"))
                db.add(o)
                db.flush()
                qn = rng.randint(2, 4)
                it = OrderItem(customer_order_id=o.customer_order_id,
                               composition_id=comp.composition_id, quantity=qn,
                               unit_price=Decimal(comp.standard_price), discount=Decimal("10"))
                db.add(it)
                db.flush()
                db.add(OrderItemColor(order_item_id=it.order_item_id,
                                      color_id=low.color_id, color_surcharge=Decimal("0")))
                o.total_price = _q(Decimal(comp.standard_price) * qn * Decimal("0.9"))
                n_orders += 1


        # --- Worker money balances: keep them roughly settled. Three partners are
        #     still owed ~EUR 100 (materials they fronted, not yet reimbursed); one
        #     carries a small ~EUR 50 debt (a cash advance to be worked off). ---
        a_supplier = suppliers[0]
        for w, target in zip(workers, (100, 95, 105, -50)):
            if target > 0:
                ex = Expense(paid_by_party_id=w.party_id,
                             paid_to_party_id=a_supplier.party_id,
                             date=date(2026, 12, 20), payment_method="card",
                             total_cost=Decimal(target),
                             comment="Materials fronted by partner, not yet reimbursed")
                db.add(ex)
                db.flush()
                db.add(ExpenseItem(expense_id=ex.expense_id,
                                   expense_category_id=materials_cat.expense_category_id,
                                   description="Balloons & supplies", quantity=1,
                                   unit_cost=Decimal(target)))
                n_exp += 1
            else:
                db.add(MoneyTransfer(
                    from_party_id=business.party_id, to_party_id=w.party_id,
                    date=date(2026, 12, 20), amount=Decimal(-target),
                    payment_method="transfer", comment="Cash advance to be worked off"))
                n_tx += 1

        db.commit()
        print("Seeded fake operational history (Sep–Dec 2026):")
        print(f"  orders: {n_orders} · expenses: {n_exp} · transfers: {n_tx} · "
              f"work sessions: {n_work} · inventory movements: {n_inv}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()