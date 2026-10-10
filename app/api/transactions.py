"""Expense, work and manual inventory-update entry."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.crud import _integrity_message
from app.db.models import (
    CustomerOrder,
    Expense,
    ExpenseItem,
    InventoryUpdate,
    InventoryUpdateItem,
    MoneyTransfer,
    User,
    Work,
)
from app.db.session import get_db
from app.schemas.transactional import (
    ExpenseCreate,
    ExpenseHeaderUpdate,
    ExpenseItemIn,
    ExpenseRead,
    InventoryUpdateCreate,
    InventoryUpdateRead,
    MoneyTransferCreate,
    MoneyTransferRead,
    MoneyTransferUpdate,
    WorkBulkCreate,
    WorkCreate,
    WorkRead,
    WorkUpdate,
)
from app.services.audit import log_action
from app.services.refill import build_refill, delete_refill, sync_refill_date


def _commit_or_400(db: Session):
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=_integrity_message(exc)) from exc


# ================================ EXPENSE ==================================
expense_router = APIRouter(prefix="/api/expense", tags=["expense"])


def _expense_items(items: list[ExpenseItemIn]) -> list[ExpenseItem]:
    return [ExpenseItem(product_id=i.product_id, customer_order_id=i.customer_order_id,
                        expense_category_id=i.expense_category_id, description=i.description,
                        variant=i.variant, quantity=i.quantity, unit_cost=i.unit_cost,
                        comment=i.comment)
            for i in items]


def _get_expense(db: Session, expense_id: int) -> Expense:
    e = db.get(Expense, expense_id)
    if e is None:
        raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")
    return e


@expense_router.get("", response_model=list[ExpenseRead])
def list_expenses(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return db.query(Expense).order_by(Expense.date.desc(), Expense.expense_id.desc()).all()


@expense_router.get("/{expense_id}", response_model=ExpenseRead)
def get_expense(expense_id: int, db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return _get_expense(db, expense_id)


@expense_router.post("", response_model=ExpenseRead, status_code=201)
def create_expense(body: ExpenseCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    computed = sum((i.quantity * i.unit_cost for i in body.items), start=Decimal(0))
    total_cost = body.total_cost if body.total_cost is not None else computed
    if total_cost <= 0 and not body.items:
        raise HTTPException(status_code=400,
                            detail="Provide a total_cost or at least one expense line.")
    expense = Expense(paid_by_party_id=body.paid_by_party_id,
                      paid_to_party_id=body.paid_to_party_id, date=body.date,
                      total_cost=total_cost, payment_method=body.payment_method,
                      comment=body.comment)
    expense.items = _expense_items(body.items)
    db.add(expense)
    _commit_or_400(db)  # flush: assigns expense_item ids used as refill provenance

    # Product lines raise stock automatically (purchase movement).
    refill = build_refill(db, expense)
    refill_lines = len(refill.items) if refill is not None else 0
    if refill is not None:
        db.add(refill)
        _commit_or_400(db)

    log_action(db, user, "create", "expense", expense.expense_id, {"items": len(expense.items)})
    if refill_lines:
        log_action(db, user, "create", "inventory_update", refill.inventory_update_id,
                   {"purchase": f"expense #{expense.expense_id}", "lines": refill_lines})
    db.commit()
    db.refresh(expense)
    return expense


@expense_router.put("/{expense_id}/items", response_model=ExpenseRead)
def replace_expense_items(expense_id: int, items: list[ExpenseItemIn],
                          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    expense = _get_expense(db, expense_id)
    # The old purchase movement references these item rows; drop it first so the
    # items can be replaced, then rebuild it from the new lines.
    delete_refill(db, expense)
    expense.items.clear()
    db.flush()
    expense.items = _expense_items(items)
    _commit_or_400(db)  # flush: assigns new expense_item ids used as refill provenance

    refill = build_refill(db, expense)
    refill_lines = len(refill.items) if refill is not None else 0
    if refill is not None:
        db.add(refill)
        _commit_or_400(db)

    log_action(db, user, "update", "expense", expense_id, {"items": len(items)})
    if refill_lines:
        log_action(db, user, "create", "inventory_update", refill.inventory_update_id,
                   {"purchase": f"expense #{expense_id}", "lines": refill_lines})
    db.commit()
    db.refresh(expense)
    return expense


@expense_router.patch("/{expense_id}", response_model=ExpenseRead)
def update_expense(expense_id: int, body: ExpenseHeaderUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    expense = _get_expense(db, expense_id)
    changes = {}
    for key, value in body.model_dump(exclude_unset=True).items():
        if getattr(expense, key) != value:
            changes[key] = {"da": getattr(expense, key), "a": value}
            setattr(expense, key, value)
    if changes:
        if "date" in changes:
            sync_refill_date(db, expense)  # keep the purchase movement's date in sync
        _commit_or_400(db)
        log_action(db, user, "update", "expense", expense_id, changes)
        db.commit()
        db.refresh(expense)
    return expense


@expense_router.delete("/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    expense = _get_expense(db, expense_id)
    summary = {"paid_to": expense.paid_to_party_id, "date": str(expense.date),
               "total": str(expense.total_cost)}
    delete_refill(db, expense)   # drop the stock refill it generated first (frees the FK)
    db.delete(expense)           # expense lines cascade
    _commit_or_400(db)
    log_action(db, user, "delete", "expense", expense_id, summary)
    db.commit()
    return {"deleted": True, "expense_id": expense_id}


# ================================= WORK ====================================
work_router = APIRouter(prefix="/api/work", tags=["work"])


def _get_work(db: Session, work_id: int) -> Work:
    w = db.get(Work, work_id)
    if w is None:
        raise HTTPException(status_code=404, detail=f"Work {work_id} not found")
    return w


@work_router.get("", response_model=list[WorkRead])
def list_work(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return db.query(Work).order_by(Work.start_at.desc().nullslast(),
                                   Work.work_id.desc()).all()


@work_router.get("/{work_id}", response_model=WorkRead)
def get_work(work_id: int, db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return _get_work(db, work_id)


def _resolve_orders(db: Session, order_ids: list[int]) -> list[CustomerOrder]:
    if not order_ids:
        return []
    found = db.query(CustomerOrder).filter(
        CustomerOrder.customer_order_id.in_(order_ids)).all()
    missing = set(order_ids) - {o.customer_order_id for o in found}
    if missing:
        raise HTTPException(status_code=400,
                            detail=f"Orders not found: {sorted(missing)}")
    return found


@work_router.post("", response_model=WorkRead, status_code=201)
def create_work(body: WorkCreate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    data = body.model_dump()
    order_ids = data.pop("order_ids", [])
    work = Work(**data)
    work.orders = _resolve_orders(db, order_ids)
    db.add(work)
    _commit_or_400(db)
    log_action(db, user, "create", "work", work.work_id, body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(work)
    return work


@work_router.post("/bulk", response_model=list[WorkRead], status_code=201)
def create_work_bulk(body: WorkBulkCreate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Log the same session for several workers at once (one Work row each)."""
    orders = _resolve_orders(db, body.order_ids)
    created: list[Work] = []
    for pid in dict.fromkeys(body.party_ids):   # de-duplicate, keep order
        work = Work(party_id=pid, start_at=body.start_at, end_at=body.end_at,
                    break_minutes=body.break_minutes,
                    tasks_accomplished=body.tasks_accomplished, comment=body.comment)
        work.orders = list(orders)
        db.add(work)
        created.append(work)
    _commit_or_400(db)
    for w in created:
        log_action(db, user, "create", "work", w.work_id, {"party_id": w.party_id, "bulk": len(created)})
    db.commit()
    for w in created:
        db.refresh(w)
    return created


@work_router.patch("/{work_id}", response_model=WorkRead)
def update_work(work_id: int, body: WorkUpdate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    work = _get_work(db, work_id)
    changes = {}
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "order_ids":
            new_ids = value or []
            if set(work.order_ids) != set(new_ids):
                changes["order_ids"] = {"da": work.order_ids, "a": new_ids}
                work.orders = _resolve_orders(db, new_ids)
            continue
        if getattr(work, key) != value:
            changes[key] = {"da": str(getattr(work, key)), "a": str(value)}
            setattr(work, key, value)
    if changes:
        _commit_or_400(db)
        log_action(db, user, "update", "work", work_id, changes)
        db.commit()
        db.refresh(work)
    return work


@work_router.delete("/{work_id}")
def delete_work(work_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    work = _get_work(db, work_id)
    summary = {"party_id": work.party_id, "start_at": str(work.start_at)}
    work.orders = []             # drop the M:N links first
    db.delete(work)
    _commit_or_400(db)
    log_action(db, user, "delete", "work", work_id, summary)
    db.commit()
    return {"deleted": True, "work_id": work_id}


# =========================== INVENTORY UPDATE ==============================
# Inventory updates are historical: created (append-only), listed, viewed.
inventory_router = APIRouter(prefix="/api/inventory_update", tags=["inventory"])


@inventory_router.get("", response_model=list[InventoryUpdateRead])
def list_updates(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return db.query(InventoryUpdate).order_by(InventoryUpdate.date.desc(),
                                              InventoryUpdate.inventory_update_id.desc()).all()


@inventory_router.get("/{update_id}", response_model=InventoryUpdateRead)
def get_update(update_id: int, db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    upd = db.get(InventoryUpdate, update_id)
    if upd is None:
        raise HTTPException(status_code=404, detail=f"Movement {update_id} not found")
    return upd


def _manual_qc(body_type: str, v: int) -> int | None:
    """What to store in quantity_change for one manual line, or None to skip it.

    A **recount stores the counted ABSOLUTE** (a checkpoint, not a delta): the
    stock derivation takes the latest recount as the base and ignores everything
    before it, so recounts are the law. `0` is a valid recount (empty) and is kept.
    Loss/gift store a signed magnitude; a `0` magnitude is a no-op and is skipped."""
    if body_type == "recount":
        if v < 0:
            raise HTTPException(status_code=400, detail="A recount quantity cannot be negative.")
        return v
    if v == 0:
        return None
    return -abs(v) if body_type == "loss" else abs(v)


@inventory_router.post("", response_model=InventoryUpdateRead, status_code=201)
def create_update(body: InventoryUpdateCreate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    # Manual stock updates are recount (absolute checkpoint), loss (-) or gift (+).
    # Purchases come from an EXPENSE (auto-refill) and consumption from an ORDER
    # (auto), so every purchase stays tracked in the money books.
    if body.type not in ("recount", "loss", "gift"):
        raise HTTPException(
            status_code=400,
            detail="Manual stock updates can only be 'recount', 'loss' or 'gift'. "
                   "Purchases are recorded via an Expense; consumption via orders.")
    lines: list[InventoryUpdateItem] = []
    for i in body.items:
        qc = _manual_qc(body.type, int(i.quantity_change))
        if qc is None:
            continue
        lines.append(InventoryUpdateItem(
            required_item_id=i.required_item_id, color_id=i.color_id, variant=i.variant,
            quantity_change=qc, comment=i.comment))
    if not lines:
        raise HTTPException(status_code=400, detail="Nothing to record.")
    upd = InventoryUpdate(type=body.type, date=body.date, comment=body.comment)
    upd.items = lines
    db.add(upd)
    _commit_or_400(db)
    log_action(db, user, "create", "inventory_update", upd.inventory_update_id,
               {"type": body.type, "lines": len(upd.items)})
    db.commit()
    db.refresh(upd)
    return upd


@inventory_router.patch("/{update_id}", response_model=InventoryUpdateRead)
def edit_update(update_id: int, body: InventoryUpdateCreate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Edit a MANUAL stock movement (recount/loss/gift). Replaces its lines.

    Only recount/loss/gift can be edited — purchase/consumption are owned by the
    related expense/order. A recount stores the counted absolute (a checkpoint);
    loss/gift store a signed magnitude."""
    upd = db.get(InventoryUpdate, update_id)
    if upd is None:
        raise HTTPException(status_code=404, detail=f"Stock update {update_id} not found")
    if upd.type not in ("recount", "loss", "gift"):
        raise HTTPException(
            status_code=400,
            detail="This movement was generated automatically (purchase/consumption). "
                   "Edit the related expense or order instead.")
    if body.type not in ("recount", "loss", "gift"):
        raise HTTPException(
            status_code=400,
            detail="Manual stock updates can only be 'recount', 'loss' or 'gift'.")
    lines: list[InventoryUpdateItem] = []
    for i in body.items:
        qc = _manual_qc(body.type, int(i.quantity_change))
        if qc is None:
            continue
        lines.append(InventoryUpdateItem(
            required_item_id=i.required_item_id, color_id=i.color_id, variant=i.variant,
            quantity_change=qc, comment=i.comment))
    if not lines:
        raise HTTPException(status_code=400, detail="Nothing to record.")
    upd.type, upd.date, upd.comment = body.type, body.date, body.comment
    upd.items = lines  # old lines are orphaned and deleted via cascade
    _commit_or_400(db)
    log_action(db, user, "update", "inventory_update", update_id,
               {"type": body.type, "lines": len(lines)})
    db.commit()
    db.refresh(upd)
    return upd


@inventory_router.delete("/{update_id}")
def delete_update(update_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    upd = db.get(InventoryUpdate, update_id)
    if upd is None:
        raise HTTPException(status_code=404, detail=f"Stock update {update_id} not found")
    # Auto movements belong to an expense/order — delete those, not the movement.
    if upd.type not in ("recount", "loss", "gift"):
        raise HTTPException(
            status_code=400,
            detail="This movement was generated automatically (purchase/consumption). "
                   "Delete the related expense or order instead.")
    db.delete(upd)  # lines cascade
    _commit_or_400(db)
    log_action(db, user, "delete", "inventory_update", update_id, {"type": upd.type})
    db.commit()
    return {"deleted": True, "inventory_update_id": update_id}


# ============================= MONEY TRANSFER ================================
# A plain cash movement between two parties (any two), not an expense or a
# sale — used to settle debts (e.g. reimbursing a fronted expense, or a
# customer paying off order revenue). Historical, append-only like expenses.
transfer_router = APIRouter(prefix="/api/money_transfer", tags=["money_transfer"])


def _get_transfer(db: Session, transfer_id: int) -> MoneyTransfer:
    t = db.get(MoneyTransfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"Money transfer {transfer_id} not found")
    return t


@transfer_router.get("", response_model=list[MoneyTransferRead])
def list_transfers(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return db.query(MoneyTransfer).order_by(
        MoneyTransfer.date.desc(), MoneyTransfer.money_transfer_id.desc()).all()


@transfer_router.get("/{transfer_id}", response_model=MoneyTransferRead)
def get_transfer(transfer_id: int, db: Session = Depends(get_db),
                 _u: User = Depends(get_current_user)):
    return _get_transfer(db, transfer_id)


@transfer_router.post("", response_model=MoneyTransferRead, status_code=201)
def create_transfer(body: MoneyTransferCreate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    transfer = MoneyTransfer(**body.model_dump())
    db.add(transfer)
    _commit_or_400(db)
    log_action(db, user, "create", "money_transfer", transfer.money_transfer_id,
               body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(transfer)
    return transfer


@transfer_router.patch("/{transfer_id}", response_model=MoneyTransferRead)
def update_transfer(transfer_id: int, body: MoneyTransferUpdate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    transfer = _get_transfer(db, transfer_id)
    changes = {}
    for key, value in body.model_dump(exclude_unset=True).items():
        if getattr(transfer, key) != value:
            changes[key] = {"da": getattr(transfer, key), "a": value}
            setattr(transfer, key, value)
    if changes:
        _commit_or_400(db)
        log_action(db, user, "update", "money_transfer", transfer_id, changes)
        db.commit()
        db.refresh(transfer)
    return transfer


@transfer_router.delete("/{transfer_id}")
def delete_transfer(transfer_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    transfer = _get_transfer(db, transfer_id)
    summary = {"from": transfer.from_party_id, "to": transfer.to_party_id,
               "amount": str(transfer.amount)}
    db.delete(transfer)
    _commit_or_400(db)
    log_action(db, user, "delete", "money_transfer", transfer_id, summary)
    db.commit()
    return {"deleted": True, "money_transfer_id": transfer_id}