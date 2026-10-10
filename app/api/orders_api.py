"""Customer-order entry: header + items + colours, and completion -> consumption."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.crud import _integrity_message
from app.db.models import (
    Color,
    Composition,
    CustomerOrder,
    ExpenseItem,
    OrderItem,
    OrderItemColor,
    OrderItemNumber,
    User,
)
from app.db.session import get_db
from app.schemas.transactional import (
    CustomerOrderCreate,
    CustomerOrderHeaderUpdate,
    CustomerOrderRead,
    OrderItemIn,
)
from app.services.audit import log_action
from app.services.consumption import (
    build_consumption,
    default_numbers,
    delete_consumption,
    number_requirements,
    order_already_consumed,
    sync_consumption_date,
)
from app.services.order_lifecycle import auto_complete_due

router = APIRouter(prefix="/api/order", tags=["order"])

# Items can be edited in any state except cancelled. Editing a completed order
# rebuilds its theoretical consumption so stock stays correct.
UNEDITABLE_STATES = {"cancelled"}
# Default number colour: silver, unless the item's balloon mix includes gold.
GOLD_CODE = "088"
SILVER_CODE = "089"


def _item_total(oi: OrderItem) -> Decimal:
    """A line's total: (unit price × qty − discount) + colour surcharges."""
    keep = Decimal(1) - Decimal(oi.discount or 0) / Decimal(100)
    base = Decimal(oi.unit_price) * oi.quantity * keep
    surcharge = sum((Decimal(c.color_surcharge or 0) * keep for c in oi.colors), Decimal(0))
    return base + surcharge


def _order_total(items: list[OrderItem]) -> Decimal:
    """The order total is, by construction, the sum of its line totals."""
    return sum((_item_total(it) for it in items), Decimal(0)).quantize(Decimal("0.01"))


def _get(db: Session, order_id: int) -> CustomerOrder:
    order = db.get(CustomerOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return order


def _color_id(db: Session, code: str) -> int | None:
    row = db.query(Color.color_id).filter(Color.code == code).first()
    return row[0] if row else None


def _missing_default_colour() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=("Cannot default the number colour: the fallback colours "
                f"(gold '{GOLD_CODE}', silver '{SILVER_CODE}') are missing from "
                "master data. Add them, or set an explicit colour on each number."))


def _build_items(db: Session, items: list[OrderItemIn]) -> list[OrderItem]:
    gold = _color_id(db, GOLD_CODE)
    silver = _color_id(db, SILVER_CODE)
    comp_ids = {it.composition_id for it in items}
    comps = ({c.composition_id: c for c in
              db.query(Composition).filter(Composition.composition_id.in_(comp_ids)).all()}
             if comp_ids else {})
    result = []
    for it in items:
        oi = OrderItem(composition_id=it.composition_id, quantity=it.quantity,
                       unit_price=it.unit_price, discount=it.discount, comment=it.comment)
        oi.colors = [OrderItemColor(color_id=c.color_id, color_percentage=c.color_percentage,
                                    color_surcharge=(c.color_surcharge or 0),
                                    comment=c.comment) for c in it.colors]
        # Default number colour follows the item's balloon mix (gold if present).
        item_color_ids = {c.color_id for c in it.colors}
        num_default = gold if (gold is not None and gold in item_color_ids) else silver
        if it.numbers:
            # A number with no explicit colour needs the default to exist; if the
            # gold/silver colours are missing from master data, fail clearly
            # instead of hitting a NOT NULL violation deep in the flush.
            if any(n.color_id is None for n in it.numbers) and num_default is None:
                raise _missing_default_colour()
            oi.numbers = [OrderItemNumber(
                required_item_id=n.required_item_id, color_id=(n.color_id or num_default),
                digit=n.digit, quantity=n.quantity, comment=n.comment) for n in it.numbers]
        else:
            # Number composition saved without digits -> default to "18" (1 and 8).
            comp = comps.get(it.composition_id)
            if comp is not None and number_requirements(comp):
                if num_default is None:
                    raise _missing_default_colour()
                oi.numbers = [OrderItemNumber(required_item_id=rid, color_id=cid,
                                              digit=digit, quantity=qty)
                              for rid, digit, qty, cid in default_numbers(comp, it.quantity, num_default)]
        result.append(oi)
    return result


@router.get("", response_model=list[CustomerOrderRead])
def list_orders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    auto_complete_due(db, user=user)  # close past confirmed orders on view
    return db.query(CustomerOrder).order_by(CustomerOrder.date.desc(),
                                            CustomerOrder.customer_order_id.desc()).all()


@router.get("/{order_id}", response_model=CustomerOrderRead)
def get_order(order_id: int, db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return _get(db, order_id)


@router.post("", response_model=CustomerOrderRead, status_code=201)
def create_order(body: CustomerOrderCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    order = CustomerOrder(
        location_id=body.location_id, customer_party_id=body.customer_party_id,
        state=body.state, event_type=body.event_type, celebrated_age=body.celebrated_age,
        celebrant_gender=body.celebrant_gender, date=body.date,
        total_price=body.total_price, comment=body.comment)
    order.items = _build_items(db, body.items)
    if order.items:
        order.total_price = _order_total(order.items)  # total must equal the line sum
    db.add(order)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=_integrity_message(exc)) from exc
    log_action(db, user, "create", "customer_order", order.customer_order_id,
               {"state": order.state, "items": len(order.items)})
    db.commit()
    db.refresh(order)
    return order


@router.put("/{order_id}/items", response_model=CustomerOrderRead)
def replace_items(order_id: int, items: list[OrderItemIn], db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    order = _get(db, order_id)
    if order.state in UNEDITABLE_STATES:
        raise HTTPException(status_code=400,
                            detail=f"Order is '{order.state}': its items cannot be edited.")
    order.items.clear()
    db.flush()
    order.items = _build_items(db, items)
    order.total_price = _order_total(order.items)  # keep the total = line sum
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=_integrity_message(exc)) from exc

    # A completed order already generated consumption: rebuild it from the new
    # items so stock stays correct.
    consumption_lines = 0
    if order.state == "completed":
        delete_consumption(db, order_id)
        update = build_consumption(db, order)
        if update is not None:
            db.add(update)
            consumption_lines = len(update.items)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=_integrity_message(exc)) from exc

    log_action(db, user, "update", "customer_order", order_id, {"items": len(items)})
    if consumption_lines:
        log_action(db, user, "create", "inventory_update", None,
                   {"order_usage": f"order #{order_id}", "lines": consumption_lines, "rebuilt": True})
    db.commit()
    db.refresh(order)
    return order


@router.patch("/{order_id}", response_model=CustomerOrderRead)
def update_order(order_id: int, body: CustomerOrderHeaderUpdate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    order = _get(db, order_id)
    updates = body.model_dump(exclude_unset=True)
    new_state = updates.get("state")
    completing = (new_state == "completed" and order.state != "completed")
    # Leaving 'completed' (-> confirmed/draft/cancelled) must undo the stock usage
    # the completion generated, or the magazzino stays wrongly depleted.
    leaving_completed = (new_state is not None and new_state != "completed"
                         and order.state == "completed")

    changes = {}
    for key, value in updates.items():
        if getattr(order, key) != value:
            changes[key] = {"da": getattr(order, key), "a": value}
            setattr(order, key, value)

    # On transition to completed, generate theoretical consumption once.
    consumption_lines = 0
    consumption_removed = False
    if completing and not order_already_consumed(db, order_id):
        update = build_consumption(db, order)
        if update is not None:
            db.add(update)
            consumption_lines = len(update.items)
    elif leaving_completed:
        delete_consumption(db, order_id)  # drop the order_usage movement
        consumption_removed = True
    # Keep an existing consumption movement's date aligned with the order date.
    if "date" in changes:
        sync_consumption_date(db, order)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=_integrity_message(exc)) from exc

    if changes:
        log_action(db, user, "update", "customer_order", order_id, changes)
    if consumption_lines:
        log_action(db, user, "create", "inventory_update", None,
                   {"order_usage": f"order #{order_id}", "lines": consumption_lines})
    if consumption_removed:
        log_action(db, user, "delete", "inventory_update", None,
                   {"order_usage": f"order #{order_id}", "reverted": True})
    db.commit()
    db.refresh(order)
    return order

@router.delete("/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    order = _get(db, order_id)
    attributed = db.query(ExpenseItem).filter(ExpenseItem.customer_order_id == order_id).count()
    if attributed:
        raise HTTPException(
            status_code=400,
            detail=(f"Cannot delete: {attributed} expense line(s) are attributed to this order. "
                    "Remove or reassign them first."))
    summary = {"state": order.state, "date": str(order.date), "total": str(order.total_price)}
    delete_consumption(db, order_id)  # its theoretical stock usage goes with it
    db.delete(order)                  # items/colours/numbers cascade; work links are unlinked
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=_integrity_message(exc)) from exc
    log_action(db, user, "delete", "customer_order", order_id, summary)
    db.commit()
    return {"deleted": True, "customer_order_id": order_id}
