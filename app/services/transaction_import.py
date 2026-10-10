"""Deterministic import of the single-document batches: stock updates, work
sessions and money transfers (see schemas/imports.py).

Same philosophy as `order_import` / `expense_import`: the JSON is a faithful
transcription; all mapping (material/colour/party names -> ids), the signed
stock delta, the work datetimes and every check are rule-based. Checks and
messages are documented in `app/import_spec/RICHIE_IMPORT_SPEC.md`; keep the two
in sync.

`analyze_*(commit=False)` is a dry-run report; `commit=True` also creates the
rows for ok+doubt entries. Commit is per-row and idempotent: re-sending a file
skips what already exists (duplicates).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.db.models import (
    InventoryUpdate,
    InventoryUpdateItem,
    MoneyTransfer,
    RequiredItem,
    Work,
)
from app.schemas.imports import (
    ImportOrderResult,
    ImportReport,
    StockBatch,
    TransfersBatch,
    WorkBatch,
)
from app.services.import_common import (
    ColorResolver,
    PartyResolver,
    commit_comment,
    parse_date,
    parse_time,
    q,
    tally,
)

STOCK_TYPES = ("recount", "loss", "gift")


# =============================== STOCK =====================================
def _item_resolver(db: Session):
    index: dict[str, list[RequiredItem]] = {}
    for it in db.query(RequiredItem).all():
        index.setdefault(it.name.strip().lower(), []).append(it)

    def resolve(written: str | None):
        key = (written or "").strip().lower()
        if not key:
            return None, "missing"
        hits = index.get(key, [])
        if len(hits) == 1:
            return hits[0], None
        return (None, "ambiguous") if hits else (None, "unknown")
    return resolve


def _line_signature(type_: str, d: date, rid, cid, variant, value) -> tuple:
    """Per-LINE signature (type, date, material, colour, digit, stored value —
    absolute for recount, signed magnitude for loss/gift). Dedup is line-level so
    a re-sent (and fixed) file doesn't re-create lines already committed."""
    return (type_, d.isoformat(), rid, cid, variant, value)


def analyze_stock(db: Session, batch: StockBatch, *, commit: bool, user=None,
                  today: date | None = None) -> ImportReport:
    resolve_item = _item_resolver(db)
    colors = ColorResolver(db)

    existing: set[tuple] = set()
    for u in db.query(InventoryUpdate).all():
        for l in u.items:
            existing.add(_line_signature(u.type, u.date, l.required_item_id,
                                         l.color_id, l.variant, l.quantity_change))
    seen: set[tuple] = set()
    # At most ONE recount per (material, colour, digit) in the whole file — two
    # recounts of the same cell would be contradictory/ambiguous.
    recount_cells: set[tuple] = set()

    results: list[ImportOrderResult] = []
    for i, upd in enumerate(batch.updates):
        messages: list[str] = []
        header_error = False

        type_ = (upd.type or "").strip().lower()
        if not type_:
            messages.append("Missing stock-update type."); header_error = True
        elif type_ not in STOCK_TYPES:
            messages.append(f"Unknown type '{upd.type}': use recount, loss or gift."); header_error = True

        d = parse_date(upd.date, today)
        if d is None:
            messages.append(f"Missing or invalid date: '{upd.date}'."); header_error = True

        if not upd.items:
            messages.append("Stock update has no lines."); header_error = True

        line_parts: list[str] = []
        built: list[InventoryUpdateItem] = []
        n_err = n_dup = n_soft = 0   # rejected / duplicate / soft-doubt lines

        for n, it in enumerate(upd.items if not header_error else [], 1):
            label = it.item or f"line {n}"

            # quantity: a recount may be 0 ("now empty"); loss/gift need > 0.
            if it.quantity is None:
                messages.append(f"Line '{label}': missing quantity."); n_err += 1; continue
            try:
                qty = int(it.quantity)
            except (ValueError, TypeError):
                messages.append(f"Line '{label}': invalid quantity."); n_err += 1; continue
            if qty < 0 or (qty == 0 and type_ != "recount"):
                need = "≥ 0" if type_ == "recount" else "> 0"
                messages.append(f"Line '{label}': quantity must be {need}."); n_err += 1; continue

            item, problem = resolve_item(it.item)
            if problem == "missing":
                messages.append(f"Line {n}: missing material name."); n_err += 1; continue
            if problem == "unknown":
                messages.append(f"Unknown material '{it.item}'."); n_err += 1; continue
            if problem == "ambiguous":
                messages.append(f"Ambiguous material '{it.item}': several materials share the name."); n_err += 1; continue

            # colour: coloured materials REQUIRE a code+name that match — never a
            # silent no-colour fallback (that would hide stock on a phantom cell).
            cid = None
            color = None
            if item.used_color:
                color, cp = colors.resolve_checked(it.color_code, it.color_name)
                if cp == "missing":
                    messages.append(f"Line '{label}': '{item.name}' is coloured — a colour code and name are required."); n_err += 1; continue
                if cp == "unknown":
                    messages.append(f"Line '{label}': unknown colour code '{it.color_code}'."); n_err += 1; continue
                if cp == "missing_name":
                    messages.append(f"Line '{label}': colour name is required (code '{it.color_code}' = '{color.name}')."); n_err += 1; continue
                if cp == "mismatch":
                    messages.append(f"Line '{label}': colour code '{it.color_code}' is '{color.name}', not '{it.color_name}' — fix the mismatch."); n_err += 1; continue
                cid = color.color_id
            elif it.color_code or it.color_name:
                messages.append(f"'{item.name}' has no colours: colour ignored."); n_soft += 1

            # digit / variant (number materials only)
            variant = None
            if it.variant not in (None, ""):
                if item.is_number and len(str(it.variant)) == 1 and str(it.variant).isdigit():
                    variant = str(it.variant)
                else:
                    messages.append(f"Line '{label}': variant '{it.variant}' ignored (needs a number material and a single digit)."); n_soft += 1
            elif item.is_number:
                messages.append(f"'{item.name}' is a number material but no digit was given: recorded without digit."); n_soft += 1

            # A recount stores the counted ABSOLUTE (a checkpoint, not a delta): the
            # stock derivation takes the latest recount as the base and ignores
            # everything before it. loss/gift store a signed magnitude.
            cell = (item.required_item_id, cid, variant)
            if type_ == "recount":
                if cell in recount_cells:
                    messages.append(f"Line '{label}': another recount in this file already sets this material/colour/digit — ambiguous."); n_err += 1; continue
                recount_cells.add(cell)
                qc = qty                 # absolute (0 = empty, kept as a checkpoint)
            elif type_ == "loss":
                qc = -qty
            else:  # gift
                qc = qty

            sig = _line_signature(type_, d, item.required_item_id, cid, variant, qc)
            if sig in seen or sig in existing:
                messages.append(f"'{item.name}': identical line already exists — skipped as duplicate."); n_dup += 1; continue
            seen.add(sig)

            cols = f" {color.code}" if color else ""
            dig = f" #{variant}" if variant else ""
            shown = f"={qc}" if type_ == "recount" else f"{'+' if qc > 0 else ''}{qc}"
            line_parts.append(f"{shown} {item.name}{cols}{dig}")
            built.append(InventoryUpdateItem(
                required_item_id=item.required_item_id, color_id=cid, variant=variant,
                quantity_change=qc, comment=it.note))

        # Status: valid lines are kept (partial commit); problems only downgrade.
        if header_error:
            status = "error"
        elif built:
            status = "ok" if (n_err == 0 and n_dup == 0 and n_soft == 0) else "doubt"
        elif n_err:
            status = "error"
        elif n_dup:
            status = "duplicate"
        else:
            status = "ok"
            messages.append("Nothing to change (every recount already matches): not created.")

        created_id = None
        if commit and status in ("ok", "doubt") and built and d is not None:
            comment = commit_comment(upd.comment, status, messages)
            row = InventoryUpdate(type=type_, date=d, comment=comment)
            row.items = built
            db.add(row); db.flush()
            created_id = row.inventory_update_id

        results.append(ImportOrderResult(
            index=i, label=f"{upd.type or '?'} · {upd.date or '?'}", status=status,
            created_id=created_id, contents=" · ".join(line_parts) or "—", messages=messages))

    if commit:
        db.commit()
    return ImportReport(
        kind=batch.kind, committed=commit, counts=tally(results),
        computed_gross_total="0.00", computed_net_total="0.00", orders=results)


# ================================ WORK =====================================
def _combine(d: date | None, s: str | None) -> datetime | None:
    t = parse_time(s)
    return datetime.combine(d, t) if (d is not None and t is not None) else None


def analyze_work(db: Session, batch: WorkBatch, *, commit: bool, user=None,
                 today: date | None = None) -> ImportReport:
    parties = PartyResolver(db)

    existing: set[tuple] = set()
    for w in db.query(Work).all():
        existing.add((w.party_id,
                      w.start_at.isoformat() if w.start_at else "",
                      w.end_at.isoformat() if w.end_at else "",
                      (w.tasks_accomplished or "").strip().lower()))
    seen: set[tuple] = set()

    results: list[ImportOrderResult] = []
    for i, e in enumerate(batch.entries):
        messages: list[str] = []
        status = "ok"

        worker, problem = parties.resolve(e.worker)
        if problem == "missing":
            messages.append("Missing worker."); status = "error"
        elif problem == "unknown":
            messages.append(f"Unknown worker: '{e.worker}'."); status = "error"
        elif problem == "ambiguous":
            messages.append(f"Ambiguous worker: '{e.worker}' matches several parties."); status = "error"
        elif not worker.is_worker:
            messages.append(f"'{worker.name}' is not flagged as a worker."); status = "error"

        d = parse_date(e.date or batch.default_date, today)
        if d is None:
            messages.append(f"Missing or invalid date: '{e.date or batch.default_date}'."); status = "error"

        start_at = _combine(d, e.start)
        end_at = _combine(d, e.end)
        if e.start and start_at is None:
            messages.append(f"Unreadable start time: '{e.start}'."); status = "error"
        if e.end and end_at is None:
            messages.append(f"Unreadable end time: '{e.end}'."); status = "error"
        if bool(e.start) != bool(e.end):
            messages.append("Only one of start/end given: duration cannot be computed.");
            if status == "ok": status = "doubt"
        if start_at and end_at and end_at < start_at:
            messages.append("End time is before start time."); status = "error"

        break_minutes = e.break_minutes
        if break_minutes is not None and break_minutes < 0:
            messages.append("Negative break ignored."); break_minutes = None
            if status == "ok": status = "doubt"

        if status != "error" and worker is not None and d is not None:
            sig = (worker.party_id, start_at.isoformat() if start_at else "",
                   end_at.isoformat() if end_at else "", (e.tasks or "").strip().lower())
            if sig in seen:
                messages.append("Duplicate: another entry in this file is identical."); status = "duplicate"
            elif sig in existing:
                messages.append("Duplicate: an identical work session already exists."); status = "duplicate"
            seen.add(sig)

        created_id = None
        if commit and status in ("ok", "doubt") and worker is not None and d is not None:
            comment = commit_comment(e.comment, status, messages)
            row = Work(party_id=worker.party_id, start_at=start_at, end_at=end_at,
                       break_minutes=break_minutes, tasks_accomplished=e.tasks, comment=comment)
            db.add(row); db.flush()
            created_id = row.work_id

        when = (start_at.strftime("%H:%M") if start_at else "?") + "–" + (end_at.strftime("%H:%M") if end_at else "?")
        brk = f", break {break_minutes}m" if break_minutes else ""
        who = worker.name if worker is not None else (e.worker or "?")
        results.append(ImportOrderResult(
            index=i, label=f"{who} · {e.date or batch.default_date or '?'}", status=status,
            created_id=created_id, contents=f"{when}{brk}" + (f" · {e.tasks}" if e.tasks else ""),
            messages=messages))

    if commit:
        db.commit()
    return ImportReport(
        kind=batch.kind, committed=commit, counts=tally(results),
        computed_gross_total="0.00", computed_net_total="0.00", orders=results)


# ============================== TRANSFERS ==================================
def analyze_transfers(db: Session, batch: TransfersBatch, *, commit: bool, user=None,
                      today: date | None = None) -> ImportReport:
    parties = PartyResolver(db)

    existing: set[tuple] = {
        (t.from_party_id, t.to_party_id, t.date.isoformat(), str(q(t.amount)))
        for t in db.query(MoneyTransfer).all()}
    seen: set[tuple] = set()

    results: list[ImportOrderResult] = []
    grand_total = Decimal(0)
    for i, t in enumerate(batch.transfers):
        messages: list[str] = []
        status = "ok"

        payer, problem = parties.resolve(t.from_party or batch.default_from)
        if problem == "missing":
            messages.append("Missing payer (no 'from_party' and no 'default_from')."); status = "error"
        elif problem:
            messages.append(f"{problem.capitalize()} payer: '{t.from_party or batch.default_from}'."); status = "error"

        payee, problem = parties.resolve(t.to_party)
        if problem == "missing":
            messages.append("Missing payee ('to_party')."); status = "error"
        elif problem:
            messages.append(f"{problem.capitalize()} payee: '{t.to_party}'."); status = "error"

        if payer is not None and payee is not None and payer.party_id == payee.party_id:
            messages.append("Payer and payee are the same party."); status = "error"

        d = parse_date(t.date, today)
        if d is None:
            messages.append(f"Missing or invalid date: '{t.date}'."); status = "error"

        try:
            amount = q(t.amount) if t.amount is not None else None
        except (InvalidOperation, ValueError):
            amount = None
        if amount is None or amount <= 0:
            messages.append("Missing or invalid amount (must be > 0)."); status = "error"

        if status != "error":
            grand_total += amount
            key = (payer.party_id, payee.party_id, d.isoformat(), str(amount))
            if key in seen:
                messages.append("Duplicate: another row of this file has the same payer, payee, date and amount."); status = "duplicate"
            elif key in existing:
                messages.append("Duplicate: an identical transfer already exists."); status = "duplicate"
            if status != "duplicate":
                seen.add(key)

        created_id = None
        if commit and status in ("ok", "doubt") and payer and payee and d and amount:
            comment = commit_comment(t.comment, status, messages)
            row = MoneyTransfer(from_party_id=payer.party_id, to_party_id=payee.party_id,
                                date=d, amount=amount, payment_method=t.payment_method, comment=comment)
            db.add(row); db.flush()
            created_id = row.money_transfer_id

        who = (f"{payer.name} → {payee.name}" if payer and payee else "?")
        results.append(ImportOrderResult(
            index=i, label=f"{t.to_party or '?'} · {t.date or '?'}", status=status,
            created_id=created_id, contents=who,
            computed_total=(str(amount) if amount is not None else None), messages=messages))

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
        orders=results)
