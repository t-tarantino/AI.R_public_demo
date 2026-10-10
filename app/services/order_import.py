"""Deterministic import of an orders batch (see schemas/imports.py).

Turns a faithful JSON transcription of a registro into DRAFT orders, resolving
everything against the live master data and reporting duplicates, errors and
doubts. Nothing is interpreted probabilistically here — the importer (or a human)
only produced the structured text; the mapping and checks are 100% rule-based.

The full list of checks and their exact messages is documented in
`app/import_spec/RICHIE_IMPORT_SPEC.md`; keep the two in sync.

Duplicate rule: there is at most ONE order per location per day. A row is a
duplicate when a non-cancelled order already exists for that (location, date)
in the database, or when an earlier row of the same file has the same
(location, date). Duplicates are skipped, never created.

`analyze(commit=False)` is a dry-run report; `commit=True` also creates the
draft orders for ok+doubt rows. Commit is per-row (not all-or-nothing) on
purpose: re-sending a corrected file skips the rows already imported.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.db.models import (
    Color,
    Composition,
    CustomerOrder,
    Location,
    OrderItem,
    OrderItemColor,
    OrderItemNumber,
)
from app.schemas.imports import ImportOrderResult, ImportReport, OrdersBatch
from app.services.consumption import default_numbers, number_requirements
from app.services.import_common import (
    PartyResolver,
    commit_comment,
    fmt_date,
    parse_date,
    q,
    tally,
    tokens,
)

LOCATION_ALIASES: dict[str, str] = {}
OFF_CATALOG_SURCHARGE = Decimal("0.10")   # off-catalogue colour adds 10% of the line base
GOLD_CODE = "088"                          # number colour when the item's mix includes gold
SILVER_CODE = "089"                        # default number colour otherwise


def _number_size_id(comp: Composition) -> int | None:
    """The required_item id of the composition's foil-number requirement, if any."""
    for req in comp.requirements:
        if req.required_item.is_number:
            return req.required_item_id
    return None


def _name_matches(written: str | None, comp_name: str) -> bool:
    """Loose match: any token sharing a prefix (handles singular/plural, short words)."""
    if not written:
        return True
    wt, ct = tokens(written), tokens(comp_name)
    if not wt or not ct:
        return True
    def share(a: str, b: str) -> bool:
        n = min(len(a), len(b), 4)
        return a[:n] == b[:n]
    return any(share(a, b) for a in wt for b in ct)


def _item_net(oi: OrderItem) -> Decimal:
    """A built line's net subtotal, identical to orders_api._item_total:
    unit price × qty − discount, plus colour surcharges (discount applies to them too)."""
    keep = Decimal(1) - Decimal(oi.discount or 0) / Decimal(100)
    base = Decimal(oi.unit_price) * oi.quantity * keep
    surcharge = sum((Decimal(c.color_surcharge or 0) * keep for c in oi.colors), Decimal(0))
    return base + surcharge


def _location_resolver(db: Session):
    index: dict[str, Location] = {}
    for loc in db.query(Location).all():
        index[loc.name.strip().lower()] = loc
        for part in loc.name.split("/"):
            index.setdefault(part.strip().lower(), loc)
    for alias, target in LOCATION_ALIASES.items():
        t = db.query(Location).filter(Location.name == target).one_or_none()
        if t:
            index[alias.strip().lower()] = t

    def resolve(written: str | None) -> Location | None:
        return index.get((written or "").strip().lower())
    return resolve


def _valid_discount(d: Decimal | None) -> bool:
    return d is None or (Decimal(0) <= d <= Decimal(100))


def analyze(db: Session, batch: OrdersBatch, *, commit: bool, user=None,
            today: date | None = None) -> ImportReport:
    resolve_loc = _location_resolver(db)
    parties = PartyResolver(db)
    comp_by_code = {c.code: c for c in db.query(Composition).all()}
    comp_by_lower = {code.lower(): comp for code, comp in comp_by_code.items()}
    color_by_code = {c.code: c for c in db.query(Color).all()}
    gold = color_by_code.get(GOLD_CODE)
    silver = color_by_code.get(SILVER_CODE)

    def resolve_comp(raw) -> Composition | None:
        """Codes are TEXT ('001', '05L', 'P01'). Match exactly (case-insensitive);
        a bare number also matches its zero-padded form ('16' -> '016')."""
        if raw is None:
            return None
        key = str(raw).strip()
        if not key:
            return None
        comp = comp_by_lower.get(key.lower())
        if comp is None and key.isdigit():
            comp = comp_by_code.get(f"{int(key):03d}")
        return comp

    batch_messages: list[str] = []
    batch_disc = batch.discount_percent
    if not _valid_discount(batch_disc):
        batch_messages.append(f"Batch discount {batch_disc}% out of range (0–100): ignored.")
        batch_disc = None
    own_discounts = any(o.discount_percent is not None for o in batch.orders)

    # internal consistency of the stated totals themselves (only meaningful with one discount)
    if (not own_discounts and batch.stated_gross_total is not None
            and batch.stated_net_total is not None):
        disc = q(batch_disc) if batch_disc is not None else Decimal(0)
        expected = q(q(batch.stated_gross_total) * (Decimal(1) - disc / Decimal(100)))
        if expected != q(batch.stated_net_total):
            batch_messages.append(
                f"Stated totals inconsistent: {q(batch.stated_gross_total)} −{disc}% = {expected}, "
                f"but stated net {q(batch.stated_net_total)}.")

    # the one-order-per-location-per-day rule: existing (non-cancelled) orders
    existing: dict[tuple[int, str], CustomerOrder] = {}
    for o in db.query(CustomerOrder).filter(CustomerOrder.state != "cancelled").all():
        existing.setdefault((o.location_id, o.date.isoformat()), o)
    seen_day_loc: set[tuple[int, str]] = set()      # within this batch

    results: list[ImportOrderResult] = []
    gross_total = net_total = Decimal(0)

    for i, order in enumerate(batch.orders):
        messages: list[str] = []
        status = "ok"

        def bump(s: str):  # raise severity to doubt, never downgrade
            nonlocal status
            if status == "ok":
                status = s

        loc = resolve_loc(order.location)
        if not order.location:
            messages.append("Missing location."); status = "error"
        elif loc is None:
            messages.append(f"Unknown location: '{order.location}'."); status = "error"
        elif getattr(loc, "active", True) is False:
            messages.append(f"Location '{loc.name}' is retired (inactive)."); bump("doubt")

        d = parse_date(order.date, today)
        if d is None:
            messages.append(f"Missing or invalid date: '{order.date}'."); status = "error"

        # customer: the order's own, else the batch default; never guessed
        cust_ref = order.customer or batch.default_customer
        customer, problem = parties.resolve(cust_ref)
        if problem == "missing":
            messages.append("Missing customer (no 'customer' on the order and no 'default_customer').")
            status = "error"
        elif problem == "unknown":
            messages.append(f"Unknown customer: '{cust_ref}'."); status = "error"
        elif problem == "ambiguous":
            messages.append(f"Ambiguous customer: '{cust_ref}' matches several parties."); status = "error"
        elif not customer.is_customer:
            messages.append(f"'{customer.name}' is not flagged as a customer."); status = "error"

        # discount: the order's own overrides the batch value
        if order.discount_percent is not None and not _valid_discount(order.discount_percent):
            messages.append(f"Discount {order.discount_percent}% out of range (0–100).")
            status = "error"
            discount = Decimal(0)
        else:
            raw = order.discount_percent if order.discount_percent is not None else batch_disc
            discount = q(raw) if raw is not None else Decimal(0)

        line_parts: list[str] = []
        order_gross = Decimal(0)              # transcribed gross: sum of the written line totals
        built_items: list[OrderItem] = []
        if not order.items:
            messages.append("Order has no lines."); status = "error"
        for it in order.items:
            if it.qty is None or it.qty <= 0 or it.line_total is None or it.line_total < 0:
                messages.append(f"Line '{it.name or it.cod or '?'}': missing/invalid quantity or total.")
                status = "error"
                continue
            try:
                qty, line_total = int(it.qty), q(it.line_total)
            except (InvalidOperation, ValueError):
                messages.append("Invalid line quantity or total."); status = "error"; continue
            order_gross += line_total
            unit_price = q(line_total / qty) if qty else Decimal(0)
            if qty and unit_price * qty != line_total:
                messages.append(f"Line '{it.name or it.cod or '?'}': {line_total}€ is not divisible "
                                f"by {qty}; unit price rounded to {unit_price}€."); bump("doubt")

            comp = resolve_comp(it.cod)
            if it.cod is None:
                messages.append(f"Item without COD ('{it.name or '?'}'): map it manually."); bump("doubt")
            elif comp is None:
                messages.append(f"COD {it.cod} ('{it.name or '?'}') not in the price list."); status = "error"
            else:
                if getattr(comp, "active", True) is False:
                    messages.append(f"COD {it.cod} ('{comp.name}') is retired (inactive)."); bump("doubt")
                if not _name_matches(it.name, comp.name):
                    # Name and COD disagreeing is unrecoverable: we cannot know which is
                    # right, so the row is rejected rather than silently trusting one.
                    messages.append(f"Name '{it.name}' doesn't match COD {it.cod} = '{comp.name}': "
                                    "fix the name or the COD."); status = "error"
                if comp.standard_price is not None and q(comp.standard_price) != unit_price:
                    messages.append(f"COD {it.cod} price: written {unit_price}€, list {q(comp.standard_price)}€."); bump("doubt")

            color_objs: list[Color] = []
            for code in it.colors:
                c = color_by_code.get(code)
                if c is None:
                    messages.append(f"Unknown colour '{code}': it will be IGNORED."); bump("doubt")
                    continue
                if getattr(c, "active", True) is False:
                    messages.append(f"Colour {c.code} {c.name} is retired (inactive)."); bump("doubt")
                if c.in_catalog is False:
                    ov = (it.color_surcharges or {}).get(c.code)
                    if ov is not None:
                        messages.append(f"Off-catalogue colour {c.code} {c.name}: surcharge set to {q(Decimal(str(ov)))}€."); bump("doubt")
                    else:
                        messages.append(f"Off-catalogue colour {c.code} {c.name}: +10% surcharge applied."); bump("doubt")
                color_objs.append(c)

            label_name = comp.name if comp else (it.name or f"COD {it.cod}")
            cols = ", ".join(f"{c.code} {c.name}" for c in color_objs) or "—"
            line_parts.append(f"{qty}× {label_name} @{unit_price}€ ({cols})")
            if comp is not None:
                line_base = unit_price * qty
                oi = OrderItem(composition_id=comp.composition_id, quantity=qty,
                               unit_price=unit_price, discount=discount or None)
                # Surcharge per colour: an explicit override wins (e.g. 0 for an
                # off-catalogue colour that wasn't surcharged); otherwise the
                # automatic +10% applies to off-catalogue colours, like by hand.
                overrides = it.color_surcharges or {}
                oi.colors = []
                for c in color_objs:
                    if c.code in overrides:
                        surcharge = q(Decimal(str(overrides[c.code])))
                    elif c.in_catalog is False:
                        surcharge = q(line_base * OFF_CATALOG_SURCHARGE)
                    else:
                        surcharge = Decimal(0)
                    oi.colors.append(OrderItemColor(color_id=c.color_id, color_surcharge=surcharge))

                # Foil numbers: build from the per-line `numbers`. Size comes from
                # the composition's number requirement; colour defaults to silver
                # (gold if the item's balloon mix includes gold). A number
                # composition with no written digits defaults to "18" (1 and 8),
                # exactly like a hand-entered order.
                size_id = _number_size_id(comp)
                item_color_ids = {c.color_id for c in color_objs}
                num_default = (gold.color_id if (gold is not None and gold.color_id in item_color_ids)
                               else (silver.color_id if silver is not None else None))
                for n in it.numbers:
                    digit = str(n.digit).strip() if n.digit is not None else ""
                    if len(digit) != 1 or not digit.isdigit():
                        messages.append(f"Number digit '{n.digit}' invalid (need one 0–9): ignored."); bump("doubt"); continue
                    if size_id is None:
                        messages.append(f"Number '{digit}' given but COD {it.cod} is not a number composition: ignored."); bump("doubt"); continue
                    ncolor = None
                    if n.color:
                        c = color_by_code.get(n.color)
                        if c is None:
                            messages.append(f"Unknown number colour '{n.color}': using the default."); bump("doubt")
                        else:
                            ncolor = c.color_id
                    ncolor = ncolor if ncolor is not None else num_default
                    if ncolor is None:
                        messages.append("Number colour default (gold/silver) missing from master data: number skipped."); bump("doubt"); continue
                    nqty = n.quantity if (n.quantity and n.quantity > 0) else 1
                    oi.numbers.append(OrderItemNumber(
                        required_item_id=size_id, color_id=ncolor, digit=digit, quantity=nqty))
                if not oi.numbers and number_requirements(comp):
                    # Number composition with no written digits -> default to "18".
                    if num_default is None:
                        messages.append(f"'{comp.name}': number colour default (gold/silver) missing from master data: digits not set."); bump("doubt")
                    else:
                        for rid, digit, nqty, cid in default_numbers(comp, qty, num_default):
                            oi.numbers.append(OrderItemNumber(
                                required_item_id=rid, color_id=cid, digit=digit, quantity=nqty))

                built_items.append(oi)

        keep = Decimal(1) - discount / Decimal(100)
        # Saved total = canonical sum of the built line subtotals (incl. surcharges),
        # exactly what orders_api derives. Lines without a usable COD are NOT saved,
        # so their money is excluded here (but still counted in the transcription below).
        order_net = q(sum((_item_net(oi) for oi in built_items), Decimal(0)))
        # Transcription net (all written lines) validates the registro's own totals.
        transcribed_net = q(order_gross * keep)
        gross_total += order_gross
        net_total += transcribed_net

        if status in ("ok", "doubt") and order.items and not built_items:
            messages.append("No line could be saved (no usable COD): the order will not be created.")

        if order.stated_total is not None and q(order.stated_total) != q(order_gross):
            messages.append(f"Order total: written {q(order.stated_total)}€, sum of lines {q(order_gross)}€."); bump("doubt")

        # one order per location per day (DB + earlier rows of this file)
        if loc is not None and d is not None:
            key = (loc.location_id, d.isoformat())
            if key in seen_day_loc:
                dup = "Duplicate: another row of this file has the same location and day."
            elif key in existing:
                ex = existing[key]
                who = ex.customer_party.name if ex.customer_party else "no customer"
                dup = (f"Duplicate: order #{ex.customer_order_id} ({ex.state}, {who}, "
                       f"{q(ex.total_price)}€) already exists for {loc.name} on {fmt_date(d)}.")
            else:
                dup = None
            if dup:
                messages.append(dup)
                if status != "error":
                    status = "duplicate"
            seen_day_loc.add(key)

        created_id = None
        if commit and status in ("ok", "doubt") and loc is not None and d is not None \
                and customer is not None and built_items:
            comment = commit_comment(order.comment, status, messages)
            co = CustomerOrder(location_id=loc.location_id,
                               customer_party_id=customer.party_id,
                               state="draft", date=d, total_price=order_net, comment=comment)
            co.items = built_items
            db.add(co); db.flush()
            created_id = co.customer_order_id

        who = f"{customer.name} · " if customer is not None else ""
        results.append(ImportOrderResult(
            index=i, label=f"{order.location or '?'} · {order.date or '?'}", status=status,
            created_order_id=created_id, contents=who + (" · ".join(line_parts) or "—"),
            computed_total=str(order_net), messages=messages))

    if commit:
        db.commit()

    gross_total, net_total = q(gross_total), q(net_total)
    checksum_ok = None
    if batch.stated_net_total is not None:
        checksum_ok = q(batch.stated_net_total) == net_total
    elif batch.stated_gross_total is not None:
        checksum_ok = q(batch.stated_gross_total) == gross_total

    return ImportReport(
        kind=batch.kind, committed=commit, counts=tally(results),
        computed_gross_total=str(gross_total), computed_net_total=str(net_total),
        stated_gross_total=(str(q(batch.stated_gross_total)) if batch.stated_gross_total is not None else None),
        stated_net_total=(str(q(batch.stated_net_total)) if batch.stated_net_total is not None else None),
        checksum_ok=checksum_ok, messages=batch_messages, orders=results)
