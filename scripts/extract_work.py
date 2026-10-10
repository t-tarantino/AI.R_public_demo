"""FASE 1 (ore di lavoro) — parsing del registro ore mensile.

Legge `data/<stagione>/work_<mese>.txt`, formato una riga per giorno:

    <Giorno> <gg> <mese>: <lavoratori> <durata> [(dalle <ora>)], <altro segmento>...

Esempi:
    Sab 29 ago: samu 1h40min (dalle 11)
    Sab 5 sett: tommy samu 3h10min, dome 2h45 (dalle 15)

Produce, in data/import_review/<stagione>/:
  * work_<mese>.csv   — una riga per (lavoratore, sessione)
  * work_<mese>.json  — struttura pronta per load_work.py
  * work_report_<mese>.md — totali per lavoratore, incongruenze.

NON scrive nel DB. Il collegamento agli ordini (per data) lo fa load_work.py.

    python -m scripts.extract_work 2026-2027 september
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "import_review"

MONTHS = {"ago": 8, "set": 9, "sett": 9, "ott": 10, "nov": 11, "dic": 12,
          "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7}

# alias del registro -> code_nickname del party (worker)
WORKER_ALIASES = {
    "dave": "DA", "dav": "DA",
    "bob": "BO", "rob": "BO",
    "alice": "AL", "ali": "AL",
    "carol": "CA", "car": "CA",
}
WORKER_NAMES = {"DA": "Dave", "BO": "Bob", "AL": "Alice", "CA": "Carol"}

DUR_RE = re.compile(r"(\d+)\s*h(?:\s*(\d+))?\s*(?:min)?", re.IGNORECASE)
TIME_RE = re.compile(r"dalle\s*(\d{1,2})(?:[.:](\d{2}))?", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{1,2})\s+([a-zA-Z]+)")


def season_year(month_num: int, season: str) -> int:
    y0, y1 = (int(p) for p in season.split("-"))
    return y0 if month_num >= 8 else y1


def parse_workers(text: str) -> list[str]:
    codes = []
    for w in re.split(r"[\s]+", text):
        key = re.sub(r"[^a-zA-Z]", "", w).lower()
        if key in WORKER_ALIASES:
            codes.append(WORKER_ALIASES[key])
    return codes


def parse_line(line: str, season: str):
    head, _, rest = line.partition(":")
    dm = DATE_RE.search(head)
    if not dm:
        return []
    day = int(dm.group(1))
    mon = MONTHS.get(dm.group(2).lower()[:4]) or MONTHS.get(dm.group(2).lower()[:3])
    year = season_year(mon, season)
    date = f"{year:04d}-{mon:02d}-{day:02d}"

    # tempo di riga (usato dai segmenti che non hanno un proprio "dalle")
    line_times = TIME_RE.findall(rest)
    line_time = line_times[-1] if line_times else None

    sessions = []
    for seg in rest.split(","):
        seg = seg.strip()
        if not seg:
            continue
        dur = DUR_RE.search(seg)
        if not dur:
            continue
        minutes = int(dur.group(1)) * 60 + (int(dur.group(2)) if dur.group(2) else 0)
        workers = parse_workers(seg[:dur.start()])
        tm = TIME_RE.search(seg)
        hm = (tm.group(1), tm.group(2)) if tm else line_time
        flags = []
        start_at = end_at = None
        if hm is not None:
            hh = int(hm[0])
            mm = int(hm[1]) if hm[1] else 0
            if hh < 7:                       # 4.30 => 16.30 (pomeriggio)
                hh += 12
                flags.append(f"ora presunta pomeridiana ({hm[0]}:{mm:02d} → {hh}:{mm:02d})")
            start = datetime.fromisoformat(f"{date}T{hh:02d}:{mm:02d}:00")
            start_at = start.isoformat()
            end_at = (start + timedelta(minutes=minutes)).isoformat()
        else:
            flags.append("orario di inizio mancante")
        for code in workers:
            sessions.append({
                "date": date, "worker_code": code, "worker_name": WORKER_NAMES.get(code, code),
                "start_at": start_at, "end_at": end_at, "duration_min": minutes,
                "break_minutes": None, "tasks_accomplished": None,
                "raw": line.strip(), "flags": list(flags),
            })
    return sessions


def parse_file(path: Path, season: str):
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.extend(parse_line(line, season))
    return out


def write_outputs(out_dir: Path, month: str, sessions: list[dict], season: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"work_{month}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["data", "lavoratore", "code", "start_at", "end_at",
                    "durata_min", "durata_h", "flags"])
        for s in sessions:
            w.writerow([s["date"], s["worker_name"], s["worker_code"], s["start_at"],
                        s["end_at"], s["duration_min"], round(s["duration_min"] / 60, 2),
                        " | ".join(s["flags"])])
    (out_dir / f"work_{month}.json").write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")

    # report
    per_worker: dict[str, int] = {}
    per_day: dict[str, int] = {}
    for s in sessions:
        per_worker[s["worker_name"]] = per_worker.get(s["worker_name"], 0) + s["duration_min"]
        per_day[s["date"]] = per_day.get(s["date"], 0) + s["duration_min"]
    total = sum(s["duration_min"] for s in sessions)

    # cross-check con gli ordini (se il mese ordini è stato estratto)
    order_days: dict[str, int] = {}
    oj = out_dir / f"{month}.json"
    if oj.exists():
        for o in json.loads(oj.read_text(encoding="utf-8")):
            order_days[o["date"]] = order_days.get(o["date"], 0) + 1

    L = [f"# Report ore di lavoro — {season} / {month}", "",
         f"- Sessioni (lavoratore × turno): **{len(sessions)}**",
         f"- Ore totali: **{round(total / 60, 2)} h**", "",
         "## Totale ore per lavoratore", "", "| Lavoratore | Ore |", "|---|--:|"]
    for name, mins in sorted(per_worker.items()):
        L.append(f"| {name} | {round(mins / 60, 2)} |")

    L += ["", "## Collegamento agli ordini (anteprima per data)", "",
          "| Data | Sessioni | Ordini quel giorno | Nota |", "|---|--:|--:|---|"]
    for d in sorted(per_day):
        n_ord = order_days.get(d)
        if n_ord is None:
            note = "⚠️ nessun ordine per quel giorno (lavoro generico o ordini mancanti)"
            n_ord_s = "0"
        else:
            note = "1:1" if n_ord == 1 else f"lavoro riferito a tutti i {n_ord} ordini"
            n_ord_s = str(n_ord)
        n_sess = sum(1 for s in sessions if s["date"] == d)
        L.append(f"| {d} | {n_sess} | {n_ord_s} | {note} |")

    flagged = [s for s in sessions if s["flags"]]
    L += ["", f"## Segnalazioni ({len(flagged)})", "",
          "| Data | Lavoratore | Flag |", "|---|---|---|"]
    for s in flagged:
        L.append(f"| {s['date']} | {s['worker_name']} | {' ; '.join(s['flags'])} |")

    (out_dir / f"work_report_{month}.md").write_text("\n".join(L), encoding="utf-8")


def main():
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-2027"
    month = (sys.argv[2] if len(sys.argv) > 2 else "september").lower()
    src = ROOT / "data" / season / f"work_{month}.txt"
    out_dir = OUT_DIR / season
    sessions = parse_file(src, season)
    write_outputs(out_dir, month, sessions, season)
    print(f"{season}/{month}: {len(sessions)} sessioni di lavoro. Output in {out_dir}")


if __name__ == "__main__":
    main()
