"""Builds the prompt that the Richie page gives to the chat.

The contract text comes straight from `app/import_spec/RICHIE_IMPORT_SPEC.md`
(single source of truth, also readable as documentation); this module only adds
a short instruction header and the live master data (the real codes the model
may use), so the prompt can never drift from the documented format.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import (
    Color,
    Composition,
    ExpenseCategory,
    Location,
    Party,
    Product,
    RequiredItem,
)

SPEC_PATH = Path(__file__).resolve().parent.parent / "import_spec" / "RICHIE_IMPORT_SPEC.md"
KINDS = ("orders", "expenses", "stock", "work", "transfers")

# Short description of each registro, used in the prompt header.
WHAT = {
    "orders": "order registro",
    "expenses": "expense registro",
    "stock": "stock-count / loss / gift note",
    "work": "work-hours registro",
    "transfers": "money-transfer (payments between people) note",
}


def spec_section(name: str) -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    m = re.search(rf"<!-- BEGIN:{name} -->(.*?)<!-- END:{name} -->", text, re.S)
    if not m:
        raise KeyError(f"spec section '{name}' not found")
    return m.group(1).strip()


def master_data(db: Session, kind: str) -> str:
    def block(title: str, rows: list[str]) -> str:
        return f"{title}\n" + ("\n".join(f"- {r}" for r in rows) if rows else "- (none)")

    parts: list[str] = []
    parties = db.query(Party).order_by(Party.name).all()
    if kind == "orders":
        parts.append(block(
            "KNOWN LOCATIONS (write the name as in the registro; the app resolves aliases)",
            [loc.name for loc in db.query(Location).filter(Location.active.is_(True)).order_by(Location.name)]))
        parts.append(block(
            "KNOWN CUSTOMERS (use the code, or the exact name)",
            [f"{p.code_nickname or '-'} = {p.name}" for p in parties if p.is_customer]))
        parts.append(block(
            "PRICE LIST (COD = name, list price)",
            [f"{int(c.code) if c.code.isdigit() else c.code} = {c.name}"
             + (f", {c.standard_price}€" if c.standard_price is not None else "")
             for c in db.query(Composition).filter(Composition.active.is_(True)).order_by(Composition.code)]))
        parts.append(block(
            "COLOURS (code = name)",
            [f"{c.code} = {c.name}" + ("" if c.in_catalog else " (off-catalogue)")
             for c in db.query(Color).filter(Color.active.is_(True)).order_by(Color.code)]))
    elif kind == "expenses":
        parts.append(block(
            "KNOWN PARTIES (use the code, or the exact name)",
            [f"{p.code_nickname or '-'} = {p.name} [" + ", ".join(
                r for r, on in (("supplier", p.is_supplier), ("worker", p.is_worker),
                                ("customer", p.is_customer), ("business", p.is_business)) if on) + "]"
             for p in parties]))
        parts.append(block(
            "EXPENSE CATEGORIES",
            [c.name for c in db.query(ExpenseCategory).order_by(ExpenseCategory.name)]))
        parts.append(block(
            "PRODUCT CODES (product_code = label)",
            [f"{p.product_code} = {p.name}" for p in
             db.query(Product).filter(Product.active.is_(True)).order_by(Product.product_code)
             if p.product_code]))
    elif kind == "stock":
        parts.append(block(
            "MATERIALS (write the name exactly; flags show what each needs)",
            [it.name + "".join(
                f" [{t}]" for t, on in (("coloured", it.used_color), ("number 0-9", it.is_number)) if on)
             for it in db.query(RequiredItem).order_by(RequiredItem.name)]))
        parts.append(block(
            "COLOURS (code = name)",
            [f"{c.code} = {c.name}" for c in
             db.query(Color).filter(Color.active.is_(True)).order_by(Color.code)]))
    elif kind == "work":
        parts.append(block(
            "WORKERS (use the code, or the exact name)",
            [f"{p.code_nickname or '-'} = {p.name}" for p in parties if p.is_worker]))
    else:  # transfers
        parts.append(block(
            "KNOWN PARTIES (anyone can be payer or payee; use the code or the exact name)",
            [f"{p.code_nickname or '-'} = {p.name}" for p in parties]))
    return "\n\n".join(parts)


def build_prompt(db: Session, kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown kind '{kind}'")
    what = WHAT[kind]
    return "\n\n".join([
        f"You convert an AI.R {what} into a JSON file for the AI.Richie importer. "
        "Reply with VALID JSON ONLY (no text before or after, no comments, no markdown). "
        "Follow the specification below EXACTLY.\n"
        f"Today's date is {date.today().isoformat()}. Use it to resolve any date written "
        "without a year (prefer writing full \"yyyy-mm-dd\" dates in the output).",
        spec_section("common"),
        spec_section(kind),
        "# MASTER DATA (live from the system)\n\n" + master_data(db, kind),
        "# REGISTRO\n\n<paste the registro text here>",
    ])
