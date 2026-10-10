"""Generic CRUD routers for master-data entities.

One factory builds the same four endpoints for every entity in the registry:

    GET    /api/{entity}          list (optional ?search= on name/code fields)
    GET    /api/{entity}/{id}     single record
    POST   /api/{entity}          create
    PATCH  /api/{entity}/{id}     partial update (also used to deactivate)

All endpoints require login. Every successful mutation writes an audit_log row
with the changed fields. Database constraint violations surface as HTTP 400 with
a readable message instead of a 500.

NOTE: no `from __future__ import annotations` here — FastAPI must see the real
schema classes in the endpoint annotations (they are closure variables, which
string annotations cannot resolve).
"""
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.base import Base
from app.db.models import (
    Color,
    Composition,
    Expense,
    ExpenseCategory,
    ExpenseItem,
    Location,
    Party,
    Product,
    RequiredItem,
    StockThreshold,
    User,
)
from app.db.session import get_db
from app.schemas import master as s
from app.services.audit import log_action


@dataclass
class EntityConfig:
    name: str                      # URL segment and audit entity name
    model: type[Base]
    pk: str                        # primary-key attribute name
    create_schema: type[BaseModel]
    update_schema: type[BaseModel]
    read_schema: type[BaseModel]
    search_fields: tuple[str, ...] = ()   # fields matched by ?search=
    order_by: tuple[str, ...] = field(default_factory=tuple)


REGISTRY: list[EntityConfig] = [
    EntityConfig("party", Party, "party_id", s.PartyCreate, s.PartyUpdate,
                 s.PartyRead, ("name", "code_nickname"), ("name",)),
    EntityConfig("location", Location, "location_id", s.LocationCreate,
                 s.LocationUpdate, s.LocationRead, ("name",), ("name",)),
    EntityConfig("color", Color, "color_id", s.ColorCreate, s.ColorUpdate,
                 s.ColorRead, ("code", "name"), ("code",)),
    EntityConfig("composition", Composition, "composition_id", s.CompositionCreate,
                 s.CompositionUpdate, s.CompositionRead, ("code", "name"), ("code",)),
    EntityConfig("expense_category", ExpenseCategory, "expense_category_id",
                 s.ExpenseCategoryCreate, s.ExpenseCategoryUpdate,
                 s.ExpenseCategoryRead, ("name",), ("name",)),
    EntityConfig("required_item", RequiredItem, "required_item_id",
                 s.RequiredItemCreate, s.RequiredItemUpdate, s.RequiredItemRead,
                 ("name",), ("name",)),
    EntityConfig("product", Product, "product_id", s.ProductCreate,
                 s.ProductUpdate, s.ProductRead, ("name", "product_code"), ("name",)),
    EntityConfig("stock_threshold", StockThreshold, "stock_threshold_id",
                 s.StockThresholdCreate, s.StockThresholdUpdate,
                 s.StockThresholdRead, (), ()),
]


def _cell_siblings(db: Session, record: Product):
    """Query for the *other* products sharing record's stock cell (NULL-safe)."""
    q = db.query(Product).filter(
        Product.required_item_id == record.required_item_id,
        Product.product_id != record.product_id,
    )
    q = q.filter(Product.color_id.is_(None) if record.color_id is None
                 else Product.color_id == record.color_id)
    q = q.filter(Product.variant.is_(None) if record.variant is None
                 else Product.variant == record.variant)
    return q


def _auto_first_choice_if_sole(db: Session, record: Product) -> None:
    """Make a product first-choice automatically when it is the only one in its
    stock cell (same required_item + colour + variant). The lone product for a
    cell is unambiguously what the Stock '+' button should open, so the user
    doesn't have to flag it by hand. Explicit flags are left untouched."""
    if record.is_first_choice:
        return
    if _cell_siblings(db, record).count() == 0:
        record.is_first_choice = True


def _enforce_single_first_choice(db: Session, record: Product) -> None:
    """Keep at most one first-choice product per stock cell.

    A cell is identified by (required_item_id, color_id, variant) — the same triple
    the Stock page '+' button matches on. When `record` is flagged first-choice,
    every *other* product in the same cell is un-flagged, so toggling one on
    automatically turns the previous one off (NULL-safe on colour/variant).
    """
    if not record.is_first_choice:
        return
    for other in _cell_siblings(db, record).filter(Product.is_first_choice.is_(True)).all():
        other.is_first_choice = False


def _threshold_duplicate_exists(db: Session, record: StockThreshold) -> bool:
    """True if another threshold already targets the same cell.

    A cell is (required_item_id, color_id, variant). The table's UNIQUE constraint
    does NOT catch this: SQL treats NULLs as distinct, so two rows with the same
    material+colour and a NULL digit (every balloon threshold) are allowed. We
    enforce it NULL-safely here so a duplicate can't create an ambiguous minimum.
    """
    q = db.query(StockThreshold).filter(
        StockThreshold.required_item_id == record.required_item_id)
    if record.stock_threshold_id is not None:
        q = q.filter(StockThreshold.stock_threshold_id != record.stock_threshold_id)
    q = q.filter(StockThreshold.color_id.is_(None) if record.color_id is None
                 else StockThreshold.color_id == record.color_id)
    q = q.filter(StockThreshold.variant.is_(None) if record.variant is None
                 else StockThreshold.variant == record.variant)
    return db.query(q.exists()).scalar()


_THRESHOLD_DUPLICATE_MSG = (
    "A threshold for this material + colour + digit already exists. "
    "Edit the existing one instead of adding a second.")


def _integrity_message(exc: IntegrityError) -> str:
    msg = str(exc.orig)
    if "UNIQUE" in msg:
        return "Duplicate value: a record with this code/name already exists."
    if "FOREIGN KEY" in msg:
        return "Invalid reference: the linked record does not exist."
    if "CHECK" in msg:
        return f"Constraint violated: {msg}"
    return f"Integrity error: {msg}"


def build_router(cfg: EntityConfig) -> APIRouter:
    router = APIRouter(prefix=f"/api/{cfg.name}", tags=[cfg.name])
    model, pk = cfg.model, cfg.pk

    def _get_or_404(db: Session, record_id: int):
        record = db.get(model, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"{cfg.name} {record_id} not found")
        return record

    @router.get("", response_model=list[cfg.read_schema])
    def list_records(
        search: str | None = Query(default=None),
        db: Session = Depends(get_db),
        _user: User = Depends(get_current_user),
    ):
        q = db.query(model)
        if search and cfg.search_fields:
            like = f"%{search}%"
            q = q.filter(or_(*(getattr(model, f).ilike(like) for f in cfg.search_fields)))
        for f in cfg.order_by:
            q = q.order_by(getattr(model, f))
        return q.all()

    @router.get("/{record_id}", response_model=cfg.read_schema)
    def get_record(
        record_id: int,
        db: Session = Depends(get_db),
        _user: User = Depends(get_current_user),
    ):
        return _get_or_404(db, record_id)

    @router.post("", response_model=cfg.read_schema, status_code=201)
    def create_record(
        body: cfg.create_schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        record = model(**body.model_dump())
        if model is StockThreshold and _threshold_duplicate_exists(db, record):
            raise HTTPException(status_code=400, detail=_THRESHOLD_DUPLICATE_MSG)
        db.add(record)
        try:
            db.flush()
            if model is Product:
                _auto_first_choice_if_sole(db, record)
                _enforce_single_first_choice(db, record)
                db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=_integrity_message(exc)) from exc
        log_action(db, user, "create", cfg.name, getattr(record, pk),
                   body.model_dump(exclude_none=True))
        db.commit()
        db.refresh(record)
        return record

    @router.patch("/{record_id}", response_model=cfg.read_schema)
    def update_record(
        record_id: int,
        body: cfg.update_schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        record = _get_or_404(db, record_id)
        updates = body.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update.")
        changes = {}
        for key, new_value in updates.items():
            old_value = getattr(record, key)
            if old_value != new_value:
                changes[key] = {"da": old_value, "a": new_value}
                setattr(record, key, new_value)
        if changes:
            if model is StockThreshold and _threshold_duplicate_exists(db, record):
                raise HTTPException(status_code=400, detail=_THRESHOLD_DUPLICATE_MSG)
            try:
                db.flush()
                if model is Product:
                    _enforce_single_first_choice(db, record)
                    db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(status_code=400, detail=_integrity_message(exc)) from exc
            action = ("deactivate"
                      if updates.get("active") is False and "active" in changes
                      else "update")
            log_action(db, user, action, cfg.name, record_id, changes)
            db.commit()
            db.refresh(record)
        return record

    return router


routers = [build_router(cfg) for cfg in REGISTRY]


# --- expense_category delete (guarded) --------------------------------------
# Categories can be created/edited via the generic CRUD; deletion needs a guard
# because expense lines reference them. If any line uses the category we refuse
# and report how many and the most recent example, so nothing is silently lost.
_ec_delete = APIRouter(prefix="/api/expense_category", tags=["expense_category"])


@_ec_delete.delete("/{record_id}")
def delete_expense_category(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cat = db.get(ExpenseCategory, record_id)
    if cat is None:
        raise HTTPException(status_code=404, detail=f"expense_category {record_id} not found")

    used = (db.query(ExpenseItem).join(Expense, ExpenseItem.expense_id == Expense.expense_id)
            .filter(ExpenseItem.expense_category_id == record_id))
    count = used.count()
    if count:
        recent = used.order_by(Expense.date.desc(), Expense.expense_id.desc()).first()
        who = recent.expense.paid_to.name if recent.expense and recent.expense.paid_to else "?"
        what = recent.description or (recent.product.name if recent.product else "—")
        when = recent.expense.date.strftime("%d/%m/%Y") if recent.expense else "?"
        raise HTTPException(
            status_code=400,
            detail=(f"Cannot delete '{cat.name}': {count} expense line(s) still use it. "
                    f"Most recent: {when} · {who} · {what}. "
                    f"Reassign or remove those expenses first."))

    db.delete(cat)
    log_action(db, user, "delete", "expense_category", record_id, {"name": cat.name})
    db.commit()
    return {"deleted": True, "expense_category_id": record_id}


routers.append(_ec_delete)