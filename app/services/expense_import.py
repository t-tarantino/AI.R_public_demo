"""Deterministic import of an expenses batch (see schemas/imports.py).

Same philosophy as `order_import`: the JSON is a faithful transcription of what
is written; mapping (party sigla/name -> party, product_code -> product,
category name -> category, unit cost = line_total / qty) and every check are
rule-based. Checks and messages are documented in
`app/import_spec/RICHIE_IMPORT_SPEC.md`; keep the two in sync.

Duplicate rule: an expense is a duplicate when another expense with the same
date, payer, payee and total already exists in the database, or when an earlier
row of the same file has the same four values. Duplicates are skipped.

Commit is per-row (not all-or-nothing) so a corrected file can be re-sent: rows
already imported are skipped as duplicates. Lines with a known product raise
stock exactly like expenses entered by hand (`build_refill`).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.db.models import Expense, ExpenseCategory, ExpenseItem, Product
from app.schemas.imports import ExpensesBatch, ImportOrderResult, ImportReport
from app.services.import_common import PartyResolver, commit_comment, parse_date, q, tally
from app.services.refill import build_refill

DEFAULT_PRODUCT_CATEGORY = "materials"


def analyze(db: Session, batch: ExpensesBatch, *, commit: bool, user=None,
            today: date | None = None) -> ImportReport:
    parties = PartyResolver(db)
    cat_by_name = {c.name.strip().lower(): c for c in db.query(ExpenseCategory).all()}
    products_by_code: dict[str, list[Product]] = {}
    for p in db.query(Product).all():
        if p.product_code:
            products_by_code.setdefault(p.product_code.strip().lower(), []).append(p)

    existing: set[tuple[str, int, int, str]] = {
        (e.date.isoformat(), e.paid_by_party_id, e.paid_to_party_id, str(q(e.total_cost)))
        for e in db.query(Expense).all()}
    seen: set[tuple[str, int, int, str]] = set()

    results: list[ImportOrderResult] = []
    grand_total = Decimal(0)

    for i, exp in enumerate(batch.expenses):
        messages: list[str] = []
        status = "ok"

        def bump(s: str):
            nonlocal status
            if status == "ok":
                status = s

        d = parse_date(exp.date, today)
        if d is None:
            messages.append(f"Missing or invalid date: '{exp.date}'."); status = "error"

        payer_ref = exp.paid_by or batch.default_paid_by
        payer, problem = parties.resolve(payer_ref)
        if problem == "missing":
            messages.append("Missing payer (no 'paid_by' and no 'default_paid_by')."); status = "error"
        elif problem:
            messages.append(f"{problem.capitalize()} payer: '{payer_ref}'."); status = "error"

        payee, problem = parties.resolve(exp.paid_to)
        if problem == "missing":
            messages.append("Missing payee ('paid_to')."); status = "error"
        elif problem:
            messages.append(f"{problem.capitalize()} payee: '{exp.paid_to}'."); status = "error"
        elif not (payee.is_supplier or payee.is_worker):
            messages.append(f"'{payee.name}' is not flagged as a supplier or worker."); bump("doubt")

        if payer is not None and payee is not None and payer.party_id == payee.party_id:
            messages.append("Payer and payee are the same party."); status = "error"

        if not exp.items:
            messages.append("Expense has no lines."); status = "error"

        line_parts: list[str] = []
        built: list[ExpenseItem] = []
        total = Decimal(0)
        for n, it in enumerate(exp.items, 1):
            label = it.description or it.product_code or f"line {n}"
            if it.qty is None or it.qty <= 0 or it.line_total is None or it.line_total < 0:
                messages.append(f"Line '{label}': missing/invalid quantity or total."); status = "error"
                continue
            try:
                qty, line_total = int(it.qty), q(it.line_total)
            except (InvalidOperation, ValueError):
                messages.append(f"Line '{label}': invalid quantity or total."); status = "error"; continue
            unit_cost = q(line_total / qty)
            if unit_cost * qty != line_total:
                messages.append(f"Line '{label}': {line_total}€ is not divisible by {qty}; "
                                f"unit cost rounded to {unit_cost}€."); bump("doubt")

            product = None
            if it.product_code:
                hits = products_by_code.get(it.product_code.strip().lower(), [])
                if len(hits) == 1:
                    product = hits[0]
                    if getattr(product, "active", True) is False:
                        messages.append(f"Product '{product.product_code}' is retired (inactive)."); bump("doubt")
                    if product.default_price is not None and q(product.default_price) != unit_cost:
                        messages.append(f"Product '{product.product_code}' cost: written {unit_cost}€, "
                                        f"usual {q(product.default_price)}€."); bump("doubt")
                elif hits:
                    messages.append(f"Product code '{it.product_code}' is ambiguous: "
                                    "line saved WITHOUT product (no stock refill)."); bump("doubt")
                else:
                    messages.append(f"Unknown product code '{it.product_code}': "
                                    "line saved WITHOUT product (no stock refill)."); bump("doubt")
            elif not it.description:
                messages.append(f"Line {n}: needs a 'product_code' or a 'description'."); status = "error"
                continue

            cat_name = it.category or (DEFAULT_PRODUCT_CATEGORY if it.product_code else None)
            if cat_name is None:
                messages.append(f"Line '{label}': missing category."); status = "error"; continue
            category = cat_by_name.get(cat_name.strip().lower())
            if category is None:
                messages.append(f"Line '{label}': unknown category '{cat_name}'."); status = "error"; continue

            variant = None
            if it.variant not in (None, ""):
                if product is not None and len(it.variant) == 1 and it.variant.isdigit():
                    variant = it.variant
                else:
                    messages.append(f"Line '{label}': variant '{it.variant}' ignored "
                                    "(needs a known product and a single digit)."); bump("doubt")

            desc = it.description or (product.name if product else it.product_code)
            line_parts.append(f"{qty}× {desc} @{unit_cost}€")
            total += unit_cost * qty   # only fully-valid lines count toward the saved total
            built.append(ExpenseItem(
                product_id=product.product_id if product else None,
                expense_category_id=category.expense_category_id,
                description=(desc or "")[:300] or None, variant=variant,
                quantity=qty, unit_cost=unit_cost, comment=it.note))

        total = q(total)
        grand_total += total
        if exp.stated_total is not None and q(exp.stated_total) != total:
            messages.append(f"Expense total: written {q(exp.stated_total)}€, sum of lines {total}€ "
                            "(the sum of lines is what gets saved)."); bump("doubt")

        if d is not None and payer is not None and payee is not None:
            key = (d.isoformat(), payer.party_id, payee.party_id, str(total))
            if key in seen:
                dup = "Duplicate: another row of this file has the same date, payer, payee and total."
            elif key in existing:
                dup = (f"Duplicate: an expense with the same date, payer, payee and total "
                       f"({total}€) already exists.")
            else:
                dup = None
            if dup:
                messages.append(dup)
                if status != "error":
                    status = "duplicate"
            if status != "error":
                seen.add(key)

        created_id = None
        if commit and status in ("ok", "doubt") and built and d and payer and payee:
            comment = commit_comment(exp.comment, status, messages)
            row = Expense(paid_by_party_id=payer.party_id, paid_to_party_id=payee.party_id,
                          date=d, total_cost=total, payment_method=exp.payment_method,
                          comment=comment)
            row.items = built
            db.add(row); db.flush()
            refill = build_refill(db, row)
            if refill is not None:
                db.add(refill); db.flush()
            created_id = row.expense_id

        who = (f"{payer.name} → {payee.name} · " if payer is not None and payee is not None else "")
        results.append(ImportOrderResult(
            index=i, label=f"{exp.paid_to or '?'} · {exp.date or '?'}", status=status,
            created_expense_id=created_id, contents=who + (" · ".join(line_parts) or "—"),
            computed_total=str(total), messages=messages))

    if commit:
        db.commit()

    grand_total = q(grand_total)
    stated = batch.stated_total
    return ImportReport(
        kind=batch.kind, committed=commit, counts=tally(results),
        computed_gross_total=str(grand_total), computed_net_total=str(grand_total),
        stated_gross_total=str(q(stated)) if stated is not None else None,
        stated_net_total=str(q(stated)) if stated is not None else None,
        checksum_ok=(q(stated) == grand_total) if stated is not None else None,
        messages=[], orders=results)
