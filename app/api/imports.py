"""Batch-import endpoints (Richie). Preview is a dry-run; commit creates rows.

All POSTs, so the app-wide `enforce_can_edit` guard already blocks read-only
accounts. Commit is per-row and idempotent: re-sending the same (or a corrected)
file creates nothing twice — rows already imported come back as duplicates.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.imports import (
    ExpensesBatch,
    ImportReport,
    OrdersBatch,
    StockBatch,
    TransfersBatch,
    WorkBatch,
)
from app.services import (
    expense_import,
    import_prompt,
    order_import,
    transaction_import,
)
from app.services.audit import log_action

router = APIRouter(prefix="/api/import", tags=["import"])


@router.get("/prompt/{kind}")
def get_prompt(kind: str, db: Session = Depends(get_db),
               _u: User = Depends(get_current_user)):
    """The chat prompt: spec + live master data. kind = orders | expenses."""
    if kind not in import_prompt.KINDS:
        raise HTTPException(status_code=404, detail="kind must be 'orders' or 'expenses'")
    return {"kind": kind, "prompt": import_prompt.build_prompt(db, kind)}


@router.post("/orders/preview", response_model=ImportReport)
def preview_orders(
    batch: OrdersBatch,
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Dry-run: resolve, validate and flag duplicates/errors/doubts. No writes."""
    return order_import.analyze(db, batch, commit=False)


@router.post("/orders/commit", response_model=ImportReport)
def commit_orders(
    batch: OrdersBatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create DRAFT orders for the ok/doubt rows (skips errors & duplicates)."""
    report = order_import.analyze(db, batch, commit=True, user=user)
    created = [r.created_order_id for r in report.orders if r.created_order_id]
    if created:
        log_action(db, user, "create", "customer_order", None,
                   {"import": "richie orders_batch", "created": len(created)})
        db.commit()
    return report


@router.post("/expenses/preview", response_model=ImportReport)
def preview_expenses(
    batch: ExpensesBatch,
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Dry-run for expenses. No writes."""
    return expense_import.analyze(db, batch, commit=False)


@router.post("/expenses/commit", response_model=ImportReport)
def commit_expenses(
    batch: ExpensesBatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create expenses (and their stock refills) for the ok/doubt rows."""
    report = expense_import.analyze(db, batch, commit=True, user=user)
    created = [r.created_expense_id for r in report.orders if r.created_expense_id]
    if created:
        log_action(db, user, "create", "expense", None,
                   {"import": "richie expenses_batch", "created": len(created)})
        db.commit()
    return report


# --- stock / work / transfers: single-document batches ----------------------
def _commit_log(db: Session, report: ImportReport, user: User, entity: str, kind: str):
    created = [r.created_id for r in report.orders if r.created_id]
    if created:
        log_action(db, user, "create", entity, None,
                   {"import": f"richie {kind}", "created": len(created)})
        db.commit()


@router.post("/stock/preview", response_model=ImportReport)
def preview_stock(batch: StockBatch, db: Session = Depends(get_db),
                  _u: User = Depends(get_current_user)):
    """Dry-run for manual stock updates (recount/loss/gift). No writes."""
    return transaction_import.analyze_stock(db, batch, commit=False)


@router.post("/stock/commit", response_model=ImportReport)
def commit_stock(batch: StockBatch, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Create the stock movements for the ok/doubt rows."""
    report = transaction_import.analyze_stock(db, batch, commit=True, user=user)
    _commit_log(db, report, user, "inventory_update", "stock_batch")
    return report


@router.post("/work/preview", response_model=ImportReport)
def preview_work(batch: WorkBatch, db: Session = Depends(get_db),
                 _u: User = Depends(get_current_user)):
    """Dry-run for work sessions. No writes."""
    return transaction_import.analyze_work(db, batch, commit=False)


@router.post("/work/commit", response_model=ImportReport)
def commit_work(batch: WorkBatch, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Create the work sessions for the ok/doubt rows."""
    report = transaction_import.analyze_work(db, batch, commit=True, user=user)
    _commit_log(db, report, user, "work", "work_batch")
    return report


@router.post("/transfers/preview", response_model=ImportReport)
def preview_transfers(batch: TransfersBatch, db: Session = Depends(get_db),
                      _u: User = Depends(get_current_user)):
    """Dry-run for money transfers. No writes."""
    return transaction_import.analyze_transfers(db, batch, commit=False)


@router.post("/transfers/commit", response_model=ImportReport)
def commit_transfers(batch: TransfersBatch, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Create the money transfers for the ok/doubt rows."""
    report = transaction_import.analyze_transfers(db, batch, commit=True, user=user)
    _commit_log(db, report, user, "money_transfer", "transfers_batch")
    return report
