"""Monthly money-flow reports: build the data, render a PDF, persist a snapshot.

A report covers one calendar month and three flows:
  * RICAVI     — completed orders (with enough detail to identify each order:
                 location, date, contents = compositions + colours + numbers).
  * SPESE      — expenses, each broken down into what was actually bought
                 (product/description × qty @ unit cost) with per-expense subtotal.
  * TRASFERIMENTI — plain cash movements between parties.

Every section carries a subtotal; a summary box on top shows revenue, expenses,
profit and the transfers total. Numbers are historical facts, so a report is a
faithful snapshot of the month.

Storage: the PDF is stored in the database (monthly_report_file) and a
MonthlyReport row records the totals. Past months are `final`; the current month
is `provisional`. `materialize()` creates the report of every closed month that
has none yet (done lazily on access). A report that exists is never rewritten
except by the manual "Regenerate" action (`ensure_report(force=True)`).
"""
from __future__ import annotations

import calendar
import io
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    CustomerOrder,
    Expense,
    MoneyTransfer,
    MonthlyReport,
    MonthlyReportFile,
    Party,
)

MONTHS_EN = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

CENTS = Decimal("0.01")

# Version of the PDF layout/content, recorded on each generated report.
# Bumping it never regenerates existing reports (only the manual action does).
#   1: initial (Italian)   2: English + daily subtotals
TEMPLATE_VERSION = 2


def month_label(year: int, month: int) -> str:
    return f"{MONTHS_EN[month]} {year}"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _q(x) -> Decimal:
    return Decimal(x or 0).quantize(CENTS)


def eur(x) -> str:
    """Format an amount, English style: €1,608.30."""
    return f"€{_q(x):,.2f}"


# --- content descriptions ----------------------------------------------------
def _order_contents(order: CustomerOrder) -> str:
    """Human summary of what an order contains: compositions, colours, numbers."""
    parts: list[str] = []
    for it in order.items:
        label = it.composition.name if it.composition else f"#{it.composition_id}"
        piece = f"{it.quantity}× {label}" if it.quantity > 1 else label
        extras: list[str] = []
        colors = [c.color.name for c in it.colors if c.color]
        if colors:
            extras.append(", ".join(colors))
        if it.numbers:
            by_color: dict[str, list[str]] = {}
            for n in it.numbers:
                by_color.setdefault(n.color.name if n.color else "?", []).append(n.digit)
            extras.append("; ".join(f"n.{''.join(d)} {col}" for col, d in by_color.items()))
        if extras:
            piece += " (" + " — ".join(extras) + ")"
        parts.append(piece)
    return " · ".join(parts) if parts else "—"


def _expense_line_label(item) -> str:
    """What a single expense line bought."""
    if item.product:
        label = item.product.name
    elif item.description:
        label = item.description
    elif item.category:
        label = item.category.name
    else:
        label = "—"
    if item.variant:
        label += f" — digit {item.variant}"
    return label

# --- data assembly -----------------------------------------------------------
def build_data(db: Session, year: int, month: int) -> dict:
    start, end = month_bounds(year, month)

    orders = (db.query(CustomerOrder)
              .filter(CustomerOrder.state == "completed",
                      CustomerOrder.date >= start, CustomerOrder.date <= end)
              .order_by(CustomerOrder.date, CustomerOrder.customer_order_id).all())
    revenue_rows = [{
        "date": o.date,
        "id": o.customer_order_id,
        "location": o.location.name if o.location else f"#{o.location_id}",
        "customer": o.customer_party.name if o.customer_party else None,
        "event": o.event_type,
        "contents": _order_contents(o),
        "amount": _q(o.total_price),
    } for o in orders]
    revenue_total = sum((r["amount"] for r in revenue_rows), Decimal(0))

    expenses = (db.query(Expense)
                .filter(Expense.date >= start, Expense.date <= end)
                .order_by(Expense.date, Expense.expense_id).all())
    expense_rows = []
    for e in expenses:
        lines = [{
            "label": _expense_line_label(it),
            "category": it.category.name if it.category else None,
            "qty": it.quantity,
            "unit_cost": _q(it.unit_cost),
            "total": _q(Decimal(it.unit_cost) * it.quantity),
        } for it in e.items]
        expense_rows.append({
            "date": e.date,
            "id": e.expense_id,
            "supplier": e.paid_to.name if e.paid_to else f"#{e.paid_to_party_id}",
            "paid_by": e.paid_by.name if e.paid_by else f"#{e.paid_by_party_id}",
            "method": e.payment_method,
            "lines": lines,
            "subtotal": _q(e.total_cost),
        })
    expense_total = sum((e["subtotal"] for e in expense_rows), Decimal(0))

    transfers = (db.query(MoneyTransfer)
                 .filter(MoneyTransfer.date >= start, MoneyTransfer.date <= end)
                 .order_by(MoneyTransfer.date, MoneyTransfer.money_transfer_id).all())
    transfer_rows = [{
        "date": t.date,
        "from": t.from_party.name if t.from_party else f"#{t.from_party_id}",
        "to": t.to_party.name if t.to_party else f"#{t.to_party_id}",
        "amount": _q(t.amount),
        "note": t.comment,
    } for t in transfers]
    transfer_total = sum((t["amount"] for t in transfer_rows), Decimal(0))

    profit_total = _q(revenue_total - expense_total)
    return {
        "year": year, "month": month, "label": month_label(year, month),
        "period": (start, end),
        "revenue_rows": revenue_rows, "revenue_total": _q(revenue_total),
        "expense_rows": expense_rows, "expense_total": _q(expense_total),
        "transfer_rows": transfer_rows, "transfer_total": _q(transfer_total),
        "profit_total": profit_total,
    }

# --- PDF rendering -----------------------------------------------------------
def render_pdf(data: dict, out, status: str) -> None:
    """Render the report PDF into `out` (a path or a binary file-like object)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    VIOLET = colors.HexColor("#7c3aed")
    SKY = colors.HexColor("#38bdf8")
    LIGHT = colors.HexColor("#f1f5f9")
    GREEN = colors.HexColor("#15803d")
    RED = colors.HexColor("#dc2626")
    GREY = colors.HexColor("#64748b")

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=8, leading=10)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7, leading=9, textColor=GREY)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=20, textColor=VIOLET, spaceAfter=2)
    sec = ParagraphStyle("sec", parent=styles["Heading2"], fontSize=12, textColor=VIOLET,
                         spaceBefore=12, spaceAfter=4)
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)
    day_sub = ParagraphStyle("day_sub", parent=right, textColor=VIOLET,
                             fontName="Helvetica-Bold", fontSize=7.5)

    doc = SimpleDocTemplate(
        out if hasattr(out, "write") else str(out), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Report {data['label']}", author="AI.R")
    W = doc.width
    flow: list = []

    # header
    badge = "FINAL" if status == "final" else "PROVISIONAL (current month)"
    flow.append(Paragraph(f"Monthly report — {data['label']}", h1))
    start, end = data["period"]
    flow.append(Paragraph(
        f"AI.R · period {start.strftime('%d/%m/%Y')} – {end.strftime('%d/%m/%Y')} "
        f"· <b>{badge}</b> · generated on {datetime.now().strftime('%d/%m/%Y %H:%M')}", small))
    flow.append(Spacer(1, 8))

    # summary box
    summary = Table([
        ["Revenue", "Expenses", "Profit", "Transfers"],
        [eur(data["revenue_total"]), eur(data["expense_total"]),
         eur(data["profit_total"]), eur(data["transfer_total"])],
    ], colWidths=[W / 4] * 4)
    profit_color = GREEN if data["profit_total"] >= 0 else RED
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VIOLET),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 11),
        ("TEXTCOLOR", (2, 1), (2, 1), profit_color),
        ("BACKGROUND", (0, 1), (-1, 1), LIGHT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBEFORE", (1, 0), (-1, -1), 0.5, colors.white),
    ]))
    flow.append(summary)


    def header_style(tbl, span_last_row=True):
        st = [
            ("BACKGROUND", (0, 0), (-1, 0), SKY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e2e8f0")),
        ]
        return st

    # --- REVENUE ---
    flow.append(Paragraph("Revenue — completed orders", sec))
    if data["revenue_rows"]:
        rows = [["Date", "#", "Location", "Details", "Amount"]]
        day_rows: list[int] = []   # indices of the per-day subtotal rows (for styling)
        for day, group in groupby(data["revenue_rows"], key=lambda r: r["date"]):
            group = list(group)
            for r in group:
                loc = r["location"] + (f"<br/><font size=6 color='#64748b'>{r['customer']}</font>" if r["customer"] else "")
                rows.append([
                    r["date"].strftime("%d/%m"), str(r["id"]),
                    Paragraph(loc, body), Paragraph(r["contents"], body),
                    Paragraph(eur(r["amount"]), right)])
            # daily subtotal, only when the day groups more than one order
            if len(group) > 1:
                day_total = sum((r["amount"] for r in group), Decimal(0))
                rows.append(["", "", "",
                             Paragraph(f"Subtotal {day.strftime('%d/%m')}", day_sub),
                             Paragraph(eur(day_total), day_sub)])
                day_rows.append(len(rows) - 1)
        rows.append(["", "", "", Paragraph("<b>Revenue subtotal</b>", right),
                     Paragraph(f"<b>{eur(data['revenue_total'])}</b>", right)])
        t = Table(rows, colWidths=[36, 22, 95, W - 36 - 22 - 95 - 70, 70], repeatRows=1)
        st = header_style(t)
        for i in day_rows:
            st += [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eef2ff")),
                   ("LINEABOVE", (0, i), (-1, i), 0.25, colors.HexColor("#c7d2fe"))]
        st += [("BACKGROUND", (0, -1), (-1, -1), LIGHT), ("LINEABOVE", (0, -1), (-1, -1), 0.75, VIOLET)]
        t.setStyle(TableStyle(st))
        flow.append(t)
    else:
        flow.append(Paragraph("No completed orders this month.", small))

    # --- EXPENSES ---
    flow.append(Paragraph("Expenses", sec))
    if data["expense_rows"]:
        for e in data["expense_rows"]:
            head = (f"<b>{e['supplier']}</b> · {e['date'].strftime('%d/%m/%Y')} "
                    f"· paid by {e['paid_by']}")
            if e["method"]:
                head += f" · {e['method']}"
            head += f" · <font color='#64748b'>expense #{e['id']}</font>"
            block: list = [Paragraph(head, body)]
            rows = [["Description", "Cat.", "Qty", "Unit price", "Total"]]
            for ln in e["lines"]:
                rows.append([
                    Paragraph(ln["label"], body),
                    Paragraph(ln["category"] or "", small),
                    str(ln["qty"]),
                    Paragraph(eur(ln["unit_cost"]), right),
                    Paragraph(eur(ln["total"]), right)])
            rows.append(["", "", "", Paragraph("<b>Subtotal</b>", right),
                         Paragraph(f"<b>{eur(e['subtotal'])}</b>", right)])
            t = Table(rows, colWidths=[W - 70 - 55 - 40 - 70, 70, 40, 70, 70], repeatRows=1)
            st = header_style(t)
            st += [("BACKGROUND", (0, -1), (-1, -1), LIGHT),
                   ("ALIGN", (2, 0), (2, -1), "CENTER")]
            t.setStyle(TableStyle(st))
            block.append(t)
            block.append(Spacer(1, 6))
            flow.append(KeepTogether(block))
        flow.append(Table([[Paragraph("<b>Expenses subtotal</b>", right),
                             Paragraph(f"<b>{eur(data['expense_total'])}</b>", right)]],
                           colWidths=[W - 90, 90],
                           style=TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.75, VIOLET),
                                             ("TOPPADDING", (0, 0), (-1, 0), 4)])))
    else:
        flow.append(Paragraph("No expenses this month.", small))

    # --- TRANSFERS ---
    flow.append(Paragraph("Money transfers", sec))
    if data["transfer_rows"]:
        rows = [["Date", "From", "To", "Note", "Amount"]]
        for tr in data["transfer_rows"]:
            rows.append([
                tr["date"].strftime("%d/%m"),
                Paragraph(tr["from"], body), Paragraph(tr["to"], body),
                Paragraph(tr["note"] or "", small),
                Paragraph(eur(tr["amount"]), right)])
        rows.append(["", "", "", Paragraph("<b>Transfers total</b>", right),
                     Paragraph(f"<b>{eur(data['transfer_total'])}</b>", right)])
        t = Table(rows, colWidths=[36, 110, 110, W - 36 - 220 - 70, 70], repeatRows=1)
        st = header_style(t)
        st += [("BACKGROUND", (0, -1), (-1, -1), LIGHT), ("LINEABOVE", (0, -1), (-1, -1), 0.75, VIOLET)]
        t.setStyle(TableStyle(st))
        flow.append(t)
    else:
        flow.append(Paragraph("No transfers this month.", small))

    doc.build(flow)

# --- persistence -------------------------------------------------------------
def _status_for(year: int, month: int, today: date | None = None) -> str:
    today = today or date.today()
    return "provisional" if (year, month) >= (today.year, today.month) else "final"

def ensure_report(db: Session, year: int, month: int, *, force: bool = False,
                  today: date | None = None) -> MonthlyReport:
    """Create the month's report if it doesn't exist yet; regenerate only if forced.

    A stored report is NEVER touched unless `force=True`, which only the manual
    "Regenerate" action passes. Not on listing, not on download, not when the
    month closes, not when the template changes.
    """
    row = (db.query(MonthlyReport)
           .filter_by(year=year, month=month).one_or_none())
    if row is not None and not force:
        return row

    status = _status_for(year, month, today)
    data = build_data(db, year, month)
    buf = io.BytesIO()
    render_pdf(data, buf, status)

    if row is None:
        row = MonthlyReport(year=year, month=month)
        db.add(row)
    row.status = status
    row.template_version = TEMPLATE_VERSION
    row.generated_at = datetime.now()
    row.revenue_total = data["revenue_total"]
    row.expense_total = data["expense_total"]
    row.transfer_total = data["transfer_total"]
    row.profit_total = data["profit_total"]
    row.order_count = len(data["revenue_rows"])
    row.expense_count = len(data["expense_rows"])
    row.transfer_count = len(data["transfer_rows"])
    row.file_path = f"db:monthly_report_file/{year}-{month:02d}.pdf"
    db.flush()  # assigns monthly_report_id

    stored = db.get(MonthlyReportFile, row.monthly_report_id)
    if stored is None:
        db.add(MonthlyReportFile(monthly_report_id=row.monthly_report_id, pdf_data=buf.getvalue()))
    else:
        stored.pdf_data = buf.getvalue()
    db.commit()
    db.refresh(row)
    return row

def stored_pdf_ids(db: Session) -> set[int]:
    """Ids of the reports whose PDF is stored (without loading the PDF bytes)."""
    return {i for (i,) in db.query(MonthlyReportFile.monthly_report_id).all()}

def get_stored_pdf(db: Session, year: int, month: int) -> bytes | None:
    """The stored PDF for a month, or None. Read-only: never generates anything."""
    row = db.query(MonthlyReport.monthly_report_id).filter_by(year=year, month=month).one_or_none()
    if row is None:
        return None
    stored = db.get(MonthlyReportFile, row[0])
    return stored.pdf_data if stored is not None else None

def _data_span(db: Session) -> tuple[date, date] | None:
    """Earliest and latest date across orders, expenses and transfers."""
    mins, maxs = [], []
    for model, col in ((CustomerOrder, CustomerOrder.date),
                       (Expense, Expense.date), (MoneyTransfer, MoneyTransfer.date)):
        lo, hi = db.query(func.min(col), func.max(col)).one()
        if lo:
            mins.append(lo)
            maxs.append(hi)
    if not mins:
        return None
    return min(mins), max(maxs)

def _iter_months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1

def materialize(db: Session, today: date | None = None) -> list[MonthlyReport]:
    """Freeze every closed month that has data but no final snapshot yet.

    This is the "automatic at month end" behaviour, run lazily whenever the
    reports list is opened. The current month is left alone (produced on demand
    as provisional). Returns the full, up-to-date list newest-first.
    """
    today = today or date.today()
    # Reports must reflect closed events: bring past confirmed orders to
    # completed first (mirrors the order-list reconciliation).
    from app.services.order_lifecycle import auto_complete_due
    auto_complete_due(db, today=today)
    span = _data_span(db)
    if span is not None:
        start, _end = span
        # only closed months: up to the last day of the previous month
        closed_end = date(today.year, today.month, 1)
        for y, m in _iter_months(date(start.year, start.month, 1), closed_end):
            if (y, m) >= (today.year, today.month):
                break
            ensure_report(db, y, m, today=today)
    return (db.query(MonthlyReport)
            .order_by(MonthlyReport.year.desc(), MonthlyReport.month.desc()).all())
