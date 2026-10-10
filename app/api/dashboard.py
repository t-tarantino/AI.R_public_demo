"""Dashboard endpoints: summary metrics, stock shortages, upcoming orders."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.stock import StockRow, compute_stock
from app.db.models import User
from app.db.session import get_db
from app.services import metrics

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class UpcomingOrder(BaseModel):
    customer_order_id: int
    location_id: int
    date: date
    state: str
    total_price: str
    item_count: int


class MoneyBalance(BaseModel):
    party_id: int
    name: str
    code_nickname: str | None
    amount: str


@router.get("/summary")
def get_summary(
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
) -> dict:
    return metrics.summary(db, start, end)


@router.get("/shortages", response_model=list[StockRow])
def get_shortages(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    return [r for r in compute_stock(db) if r.below_minimum]


@router.get("/upcoming", response_model=list[UpcomingOrder])
def get_upcoming(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    return [
        UpcomingOrder(
            customer_order_id=o.customer_order_id, location_id=o.location_id,
            date=o.date, state=o.state, total_price=str(o.total_price),
            item_count=len(o.items))
        for o in metrics.upcoming_orders(db, date.today(), days)
    ]


@router.get("/balances", response_model=list[MoneyBalance])
def get_balances(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """Money the business owes back to each party that fronted an expense."""
    return [
        MoneyBalance(
            party_id=r["party_id"], name=r["name"], code_nickname=r["code_nickname"],
            amount=str(r["amount"]))
        for r in metrics.money_balances(db)
    ]
