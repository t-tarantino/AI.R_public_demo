"""FASE 3 (dati correnti) — carica nel DB un mese già estratto e revisionato.

Legge `data/import_review/<stagione>/<mese>.json` (prodotto da extract_month.py)
e crea customer_order / order_item / order_item_color nel database.

È **idempotente**: prima di inserire, elimina gli ordini già importati per quello
stesso mese (riconosciuti dal tag di provenienza nel campo `comment`), così può
essere rilanciato senza duplicare.

    python -m scripts.load_month 2026-2027 september

ATTENZIONE: NON rilanciare `scripts.import_data` dopo aver caricato transazioni
reali: azzera tutte le tabelle business (ordini inclusi). Vedi STATO_IMPORT.md.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.db.models import (
    Color,
    Composition,
    CustomerOrder,
    Location,
    OrderItem,
    OrderItemColor,
    Party,
)
from app.db.session import SessionLocal

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER_LOCATION = "DA DEFINIRE"
CUSTOMER_CODE = "RVH"          # Riverside Hall è il cliente di tutti gli ordini AI.R


def _dec(x) -> Decimal:
    return Decimal(str(round(float(x), 2)))


def load(season: str, month: str) -> None:
    src = ROOT / "data" / "import_review" / season / f"{month}.json"
    orders = json.loads(src.read_text(encoding="utf-8"))
    tag_prefix = f"[import:{season} {month[:3]} "

    db = SessionLocal()
    try:
        loc_by_name = {l.name.upper(): l for l in db.query(Location)}
        comp_by_code = {c.code: c for c in db.query(Composition)}
        color_by_code = {c.code: c for c in db.query(Color)}
        placeholder = loc_by_name[PLACEHOLDER_LOCATION.upper()]
        customer = db.query(Party).filter_by(code_nickname=CUSTOMER_CODE).one_or_none()

        # idempotenza: rimuovi gli ordini già importati per questo mese
        existing = db.query(CustomerOrder).filter(
            CustomerOrder.comment.like(tag_prefix + "%")).all()
        for o in existing:
            db.delete(o)
        db.flush()

        n_orders = n_items = n_colors = 0
        warnings: list[str] = []
        grand_total = Decimal("0")

        for o in orders:
            loc = (loc_by_name.get((o["location"] or "").upper())
                   if o["location"] else None) or placeholder
            order_total = Decimal("0")
            evt_date = date.fromisoformat(o["date"])
            order = CustomerOrder(
                location_id=loc.location_id,
                customer_party_id=customer.party_id if customer else None,
                # Past/today events are completed; future events are confirmed.
                state="completed" if evt_date <= date.today() else "confirmed",
                event_type=None,
                date=evt_date,
                total_price=Decimal("0"),   # aggiornato sotto
                comment=o["provenance"],
            )

            for it in o["items"]:
                comp = comp_by_code.get(it["comp_code"])
                if comp is None:
                    warnings.append(
                        f"{o['date']} {o['location']}: composizione "
                        f"{it['comp_code']!r} inesistente — voce SALTATA ({it['raw']})")
                    continue
                unit = _dec(it["unit_price"])
                qty = int(it["qty"])
                disc = _dec(it["discount"])
                item_comment = " | ".join(
                    filter(None, [it.get("number_info")] + it.get("notes", []))) or None

                oi = OrderItem(composition_id=comp.composition_id, quantity=qty,
                               unit_price=unit, discount=disc, comment=item_comment)

                # dedup colori per (colore) rispettando UNIQUE(order_item, color)
                merged: dict[int, Decimal] = {}
                for c in it["colors"]:
                    if not c.get("code"):
                        continue
                    col = color_by_code.get(c["code"])
                    if col is None:
                        warnings.append(
                            f"{o['date']} {o['location']}: colore {c['raw']!r} "
                            f"(code {c['code']}) inesistente — colore SALTATO")
                        continue
                    merged[col.color_id] = merged.get(col.color_id, Decimal("0")) + _dec(c["surcharge"])
                for color_id, surch in merged.items():
                    oi.colors.append(OrderItemColor(
                        color_id=color_id, color_percentage=None, color_surcharge=surch))
                    n_colors += 1

                # totale storico effettivo della riga (netto sconto), sui valori scritti
                line_gross = unit * qty + sum(merged.values())
                line_net = (line_gross * (Decimal("100") - disc) / Decimal("100"))
                order_total += line_net
                order.items.append(oi)
                n_items += 1

            order.total_price = _dec(order_total)
            grand_total += order.total_price
            db.add(order)
            n_orders += 1

        db.commit()
        print(f"Caricato {season}/{month}: {n_orders} ordini, {n_items} voci, "
              f"{n_colors} righe colore.")
        print(f"  Totale netto ordini: € {grand_total:.2f}")
        if warnings:
            print(f"  Avvisi ({len(warnings)}):")
            for w in warnings:
                print("   -", w)
    finally:
        db.close()


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-2027"
    month = (sys.argv[2] if len(sys.argv) > 2 else "september").lower()
    load(season, month)


if __name__ == "__main__":
    main()
