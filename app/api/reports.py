"""Monthly report endpoints: list reports, (re)generate, download the PDF.

Opening the list lazily creates every closed month that has data but no
report yet (see services.monthly_report.materialize). An existing report is
never rewritten automatically: only POST .../generate (the Regenerate button)
replaces it, and the PDF download only reads what is stored.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import MonthlyReport, User
from app.db.session import get_db
from app.services import monthly_report as mr

router = APIRouter(prefix="/api/monthly_report", tags=["monthly_report"])


class MonthlyReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    monthly_report_id: int
    year: int
    month: int
    label: str
    status: str
    generated_at: datetime
    revenue_total: str
    expense_total: str
    transfer_total: str
    profit_total: str
    order_count: int
    expense_count: int
    transfer_count: int
    has_pdf: bool

    @classmethod
    def of(cls, r: MonthlyReport, has_pdf: bool) -> "MonthlyReportRead":
        return cls(
            monthly_report_id=r.monthly_report_id, year=r.year, month=r.month,
            label=mr.month_label(r.year, r.month), status=r.status,
            generated_at=r.generated_at,
            revenue_total=str(r.revenue_total), expense_total=str(r.expense_total),
            transfer_total=str(r.transfer_total), profit_total=str(r.profit_total),
            order_count=r.order_count, expense_count=r.expense_count,
            transfer_count=r.transfer_count, has_pdf=has_pdf)


@router.get("", response_model=list[MonthlyReportRead])
def list_reports(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """All reports, newest first. Creates any missing closed month first."""
    rows = mr.materialize(db)
    with_pdf = mr.stored_pdf_ids(db)
    return [MonthlyReportRead.of(r, r.monthly_report_id in with_pdf) for r in rows]


@router.post("/{year}/{month}/generate", response_model=MonthlyReportRead)
def generate_report(
    year: int, month: int,
    db: Session = Depends(get_db), _u: User = Depends(get_current_user),
):
    """Manually (re)generate one month, replacing its stored PDF. Only ever called
    by the explicit "Regenerate" button."""
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1..12")
    return MonthlyReportRead.of(mr.ensure_report(db, year, month, force=True), True)


@router.get("/{year}/{month}/pdf")
def download_pdf(
    year: int, month: int,
    db: Session = Depends(get_db), _u: User = Depends(get_current_user),
):
    """Return the stored PDF exactly as it was generated. Read-only: never regenerates."""
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1..12")
    pdf = mr.get_stored_pdf(db, year, month)
    if pdf is None:
        raise HTTPException(
            status_code=404,
            detail="No stored PDF for this month. Use Regenerate to create it.")
    filename = f"AI.R_report_{year}-{month:02d}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
