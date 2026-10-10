"""FASE 3 (spese) — carica nel DB un mese di spese gia' estratto.

Legge `data/import_review/<stagione>/expenses_<mese>.json` (da extract_expenses)
e crea expense / expense_item:
- paid_by = Riverside Hall (RVH)  → ha pagato i materiali;
- paid_to = fornitore (AMZ/FMG);
- categoria = materials; product_id collegato via product_code;
- total_cost = somma delle voci (fonte di verita').

Idempotente: rimuove le spese gia' importate per quel mese (tag nel `comment`).

    python -m scripts.load_expenses 2026-2027 september
"""
from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.db.models import (
    Expense,
    ExpenseCategory,
    ExpenseItem,
    Party,
    Product,
)
from app.db.session import SessionLocal

ROOT = Path(__file__).resolve().parent.parent
PAYER_CODE = "RVH"            # Riverside Hall ha pagato
CATEGORY = "materials"


def _dec(x) -> Decimal:
    return Decimal(str(round(float(x), 2)))


def load(season: str, month: str) -> None:
    src = ROOT / "data" / "import_review" / season / f"expenses_{month}.json"
    expenses = json.loads(src.read_text(encoding="utf-8"))
    tag_prefix = f"[import:{season} exp {month[:3]} "

    db = SessionLocal()
    try:
        party_by_code = {p.code_nickname: p for p in db.query(Party) if p.code_nickname}
        product_by_code = {p.product_code: p for p in db.query(Product) if p.product_code}
        category = db.query(ExpenseCategory).filter_by(name=CATEGORY).one()
        payer = party_by_code[PAYER_CODE]

        # idempotenza
        for e in db.query(Expense).filter(Expense.comment.like(tag_prefix + "%")).all():
            db.delete(e)
        db.flush()

        n_exp = n_items = 0
        warnings: list[str] = []
        grand = Decimal("0")
        for e in expenses:
            supplier = party_by_code.get(e["supplier_code"])
            if supplier is None:
                warnings.append(f"{e['date']}: fornitore {e['supplier_code']} inesistente — SALTATO")
                continue
            # pagante: per-spesa se indicato (es. socio che anticipa), altrimenti Riverside Hall
            payer_p = party_by_code.get(e.get("paid_by_code", PAYER_CODE), payer)
            note = e.get("note") or ("pagato da Riverside Hall, materiali usati da AI.R"
                                     if payer_p is payer else None)
            exp = Expense(
                paid_by_party_id=payer_p.party_id,
                paid_to_party_id=supplier.party_id,
                date=date.fromisoformat(e["date"]),
                total_cost=_dec(e["total_cost"]),
                payment_method=None,
                comment=e["provenance"] + (f" | {note}" if note else ""),
            )
            for it in e["items"]:
                prod = product_by_code.get(it.get("product_code"))
                if prod is None:
                    warnings.append(f"{e['date']}: prodotto {it.get('product_code')} inesistente")
                desc = f"{it['raw_name']}"
                if it.get("seller"):
                    desc = f"{desc} — {it['seller']}"
                exp.items.append(ExpenseItem(
                    product_id=prod.product_id if prod else None,
                    customer_order_id=None,
                    expense_category_id=category.expense_category_id,
                    description=desc[:300],
                    quantity=int(it["quantity"]),
                    unit_cost=_dec(it["unit_cost"]),
                    comment=None,
                ))
                n_items += 1
            db.add(exp)
            grand += _dec(e["total_cost"])
            n_exp += 1

        db.commit()
        print(f"Caricato {season}/{month}: {n_exp} spese, {n_items} voci. Totale € {grand:.2f}")
        for w in warnings:
            print("  -", w)
    finally:
        db.close()


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-2027"
    month = (sys.argv[2] if len(sys.argv) > 2 else "september").lower()
    load(season, month)


if __name__ == "__main__":
    main()
