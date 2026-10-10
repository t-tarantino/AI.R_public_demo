"""FASE 3 (ore di lavoro) — carica nel DB un mese di ore già estratto.

Legge `data/import_review/<stagione>/work_<mese>.json` e crea righe `work`,
collegando ogni sessione a TUTTI i customer_order della stessa data (M:N):
un turno copre normalmente tutte le composizioni fatte quel giorno. Se il giorno
ha un solo ordine è di fatto 1:1; se non ha ordini la sessione resta generica.

Idempotente: rimuove le ore già importate per quel mese (tag nel `comment`).

    python -m scripts.load_work 2026-2027 september
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from app.db.models import CustomerOrder, Party, Work
from app.db.session import SessionLocal

ROOT = Path(__file__).resolve().parent.parent


def _dt(x):
    return datetime.fromisoformat(x) if x else None


def load(season: str, month: str) -> None:
    src = ROOT / "data" / "import_review" / season / f"work_{month}.json"
    sessions = json.loads(src.read_text(encoding="utf-8"))
    tag_prefix = f"[import:{season} work {month[:3]} "

    db = SessionLocal()
    try:
        party_by_code = {p.code_nickname: p for p in db.query(Party)
                         if p.code_nickname}
        orders_by_date: dict[str, list[CustomerOrder]] = defaultdict(list)
        for o in db.query(CustomerOrder):
            orders_by_date[o.date.isoformat()].append(o)

        # idempotenza
        for w in db.query(Work).filter(Work.comment.like(tag_prefix + "%")).all():
            db.delete(w)
        db.flush()

        n = n_links = 0
        general = []
        warnings = []
        for s in sessions:
            party = party_by_code.get(s["worker_code"])
            if party is None:
                warnings.append(f"{s['date']}: lavoratore {s['worker_code']} inesistente — SALTATO")
                continue
            dd = date.fromisoformat(s["date"])
            linked = orders_by_date.get(s["date"], [])
            work = Work(
                party_id=party.party_id,
                start_at=_dt(s["start_at"]), end_at=_dt(s["end_at"]),
                break_minutes=s.get("break_minutes"),
                tasks_accomplished=s.get("tasks_accomplished"),
                comment=f"[import:{season} work {month[:3]} d={dd.day:02d}/{dd.month:02d} "
                        f"{s['worker_code']}]",
            )
            work.orders = list(linked)
            db.add(work)
            n += 1
            n_links += len(linked)
            if not linked:
                general.append(s["date"])

        db.commit()
        print(f"Caricato {season}/{month}: {n} sessioni di lavoro, {n_links} collegamenti a ordini.")
        if general:
            print(f"  Sessioni generiche (nessun ordine quel giorno): {len(general)} "
                  f"→ date {sorted(set(general))}")
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
