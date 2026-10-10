"""FASE 1 (dati correnti) — parsing dei file mensili 'data/<stagione>/<mese>.txt'.

Formato testo con emoji, un blocco per giorno:
    📆 <giorno> <gg/mm>
    📍 <LOCATION>
    ➡️ [COD n —] <Nome composizione> → <prezzo>€
    🎨 <colori>            (riferiti all'ultima ➡️)
    🔢 <colore numero>
    ⚠️ <sovrapprezzo>      ⭢ flag
    🎁 <omaggio>
    💰 <totali>            (usati per il cross-check)
    🏷️ <sconto>
    ⸻ separatore

NON scrive nel DB. Produce, in data/import_review/<stagione>/:
  * orders_<mese>.csv   — un ordine per (data, location)
  * items_<mese>.csv    — una riga per composizione venduta (order_item)
  * <mese>.json         — struttura annidata pronta per il loader
  * report_<mese>.md    — incongruenze + cross-check dei totali

    python -m scripts.extract_month 2026-2027 september
"""
from __future__ import annotations

import csv
import json
import re
import sys
import tomllib
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "master_data.toml"

E_DAY, E_LOC, E_ITEM = "📆", "📍", "➡️"
E_COLOR, E_NUM, E_WARN = "🎨", "🔢", "⚠️"
E_GIFT, E_MONEY, E_TAG = "🎁", "💰", "🏷️"

MONTHS = {"september": 9, "october": 10, "november": 11, "december": 12,
          "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
          "june": 6, "july": 7, "august": 8}

# Sconto standard applicato a tutti gli ordini di quest'anno (partner Riverside Hall).
DEFAULT_DISCOUNT = 10
# Normalizzazioni location note (il file usa nomi abbreviati/ambigui).
LOCATION_ALIASES = {"IGLOO": "IGLOO BIG"}


def _truthy(v, default=True):
    if v is None:
        return default
    return str(v).strip().lower() in {"true", "1", "yes", "si", "sì"}


def load_master():
    with MASTER.open("rb") as fh:
        d = tomllib.load(fh)
    colors_by_code = {c["code"]: c["name"] for c in d.get("color", [])}
    colors_by_name = {c["name"].lower(): c["code"] for c in d.get("color", [])}
    in_catalog = {c["code"]: _truthy(c.get("in_catalog"), True) for c in d.get("color", [])}
    comps = {c["code"]: c for c in d.get("composition", [])}
    locations = {l["name"].upper() for l in d.get("location", [])}
    return colors_by_code, colors_by_name, in_catalog, comps, locations


def money(s: str) -> float | None:
    m = re.search(r"[\d.,]+", s)
    if not m:
        return None
    # convenzione italiana: '.' migliaia, ',' decimali
    return float(m.group(0).replace(".", "").replace(",", "."))


def strip_lead_emoji(s: str) -> str:
    out = s.strip()
    while out and (unicodedata.category(out[0]) in {"So", "Sk"} or out[0] in "️"):
        out = out[1:].strip()
    return out


# --- risoluzione composizione da testo libero -------------------------------
def resolve_comp(text: str, comps: dict):
    t = text.lower()
    size = "L" if "200" in t else "M" if "150" in t else "S" if "100" in t else None
    flags = []

    def ok(code):
        name = comps.get(code, {}).get("name", "?")
        return code, name, flags

    if "combo" in t:
        m = re.search(r"p0?(\d)", t)
        if m:
            return ok(f"P0{m.group(1)}")
    if "nuvolette a soffitto" in t or "nuvoletta a soffitto" in t:
        return ok("011")            # NB: nel txt talvolta 'COD 17' = 011 (ex codice)
    if "nuvoletta con numero" in t:
        return ok("012")
    if "numero" in t and ("elio" in t):
        return ok("017")
    if "numero" in t and ("aria" in t or "gonfiato ad aria" in t):
        return ok("NMA")
    if "numero maxi" in t:
        return ok("014")
    if "palloncini a led" in t or ("led" in t and "palloncini" in t):
        code, name, _ = ok("015")       # trattati come Palloncini Elio
        return code, name, ["nota: palloncini a LED forniti dal festeggiato"]
    if "palloncini a pavimento" in t or "a pavimento" in t:
        return ok("PVM")
    if "palloncini" in t and "elio" in t:
        return ok("015")
    if "grappolo" in t:
        return ok("016")
    if "mezzo arco organico" in t:
        return ok("001")
    if "arco maxi organico" in t:
        return ok("003")
    if "arco maxi" in t or ("arco" in t and "maxi" in t):
        return ok("002")
    if "arco quadrato" in t:
        return ok("004")
    if "mezzo backdrop" in t:
        return ok("007")
    if "backdrop small con fiori" in t:
        return ok("010")
    if "backdrop small" in t:
        return ok("009")
    if "backdrop" in t:
        return ok("008")
    if "colonne organiche" in t or "colonna organica" in t or "organiche" in t:
        return ok(f"06{size}") if size else ("06?", "Colonne Organiche (taglia?)", ["taglia mancante"])
    if "colonn" in t or "piena" in t or "piene" in t:
        return ok(f"05{size}") if size else ("05?", "Colonne semplici (taglia?)", ["taglia mancante"])
    if "centrotavola" in t:
        return ok("013")
    if "tendina" in t:
        return ok("TND")
    flags.append("NON RICONOSCIUTA — mappare a mano")
    return "?", text, flags


def parse_qty(text: str) -> int | None:
    # 'cifre' ha priorità; '×N' solo se N non è un prezzo (non seguito da €).
    for rx in (r"(\d+)\s*cifre", r"[x×]\s*(\d+)(?!\s*€)", r"^(\d+)\s+[A-Za-z]"):
        m = re.search(rx, text)
        if m:
            return int(m.group(1))
    return None


KNOWN_UNIT = {"011": 6.0, "015": 3.0, "017": 12.0, "NMA": 5.0, "013": 12.0}


def parse_colors(text: str, by_code, by_name, in_catalog):
    """Ritorna (colori_composizione, nota_colore_numero).

    Ogni colore ha: code, raw, status ('ok' | 'fuori catalogo' | 'SCONOSCIUTO'),
    in_catalog (bool), surcharge (€, riempito dopo), surcharge_pct (se '(+N%)').
    """
    out = []
    number_note = None
    for tok in re.split(r"[,/]", text):
        tok = tok.strip()
        if not tok:
            continue
        low = tok.lower()
        if "colore numero" in low or "colore del numero" in low:
            number_note = tok            # è il colore del NUMERO, non del pezzo
            continue
        pct = None
        mp = re.search(r"\+\s*(\d+)\s*%", tok)
        if mp:
            pct = int(mp.group(1))
        clean = re.sub(r"\(.*?\)", "", tok).strip()   # via i parentetici
        m = re.match(r"(\d{3})\b\s*(.*)", clean)
        code = m.group(1) if m else by_name.get(clean.lower())
        if code is None:
            status, incat = "SCONOSCIUTO", False
        else:
            incat = in_catalog.get(code, True)
            status = "ok" if incat else "fuori catalogo"
        out.append({"code": code, "raw": tok, "status": status,
                    "in_catalog": incat, "surcharge": 0.0, "surcharge_pct": pct})
    return out, number_note


def parse_file(path: Path, season: str, month: str):
    by_code, by_name, in_catalog, comps, locations = load_master()
    y0, y1 = (int(p) for p in season.split("-"))
    mnum = MONTHS[month]
    year = y0 if mnum >= 9 else y1

    orders = {}        # (date, loc) -> order dict
    order_seq = []     # keep insertion order
    money_lines = []
    cur_date = cur_loc = None
    cur_item = None

    def get_order(date, loc):
        key = (date, loc)
        if key not in orders:
            orders[key] = {"date": date, "location": loc, "items": [],
                           "declared_total": None}
            order_seq.append(key)
        return orders[key]

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(E_DAY):
            m = re.search(r"(\d{1,2})/(\d{1,2})", line)
            cur_date = f"{year:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None
            cur_loc = None
            cur_item = None
        elif line.startswith(E_LOC):
            raw_loc = strip_lead_emoji(line)
            cur_loc = LOCATION_ALIASES.get(raw_loc.upper(), raw_loc)
            cur_item = None
        elif line.startswith(E_ITEM):
            body = strip_lead_emoji(line)
            name_part, _, price_part = body.partition("→")
            name = re.sub(r"COD\s*\d+\s*[—\-]\s*", "", name_part).strip()
            line_total = money(price_part)
            code, cname, flags = resolve_comp(body, comps)
            qty = parse_qty(body)
            if qty is None and code in KNOWN_UNIT and line_total is not None:
                u = KNOWN_UNIT[code]
                if abs((line_total / u) - round(line_total / u)) < 1e-6:
                    qty = int(round(line_total / u))
            if qty is None:
                qty = 1
            unit_price = round(line_total / qty, 2) if line_total is not None else None
            # confronto col prezzo di listino
            std = comps.get(code, {}).get("standard_price")
            if std is not None and unit_price is not None:
                if abs(float(std) - unit_price) > 0.01:
                    flags.append(f"prezzo {unit_price}€ ≠ listino {std}€")
            # separa le note informative ("nota: ...") dai flag di problema
            notes = [f[5:].strip() for f in flags if f.startswith("nota:")]
            flags = [f for f in flags if not f.startswith("nota:")]
            cur_item = {"raw": body, "comp_code": code, "comp_name": cname,
                        "qty": qty, "unit_price": unit_price, "discount": DEFAULT_DISCOUNT,
                        "list_price": line_total, "surcharge": 0.0,
                        "line_total": line_total, "colors": [],
                        "number_info": None, "notes": notes, "flags": flags}
            get_order(cur_date, cur_loc)["items"].append(cur_item)
        elif line.startswith(E_COLOR) and cur_item is not None:
            cols, num_note = parse_colors(strip_lead_emoji(line), by_code, by_name, in_catalog)
            cur_item["colors"] = cols
            if num_note and not cur_item["number_info"]:
                cur_item["number_info"] = num_note
            # Sovrapprezzo INCORPORATO nel prezzo: colore con '(+N%)'. Il prezzo
            # scritto include già il +N%: lo scorporo (base + sovrapprezzo).
            for c in cols:
                if c["surcharge_pct"] and cur_item["line_total"] is not None:
                    pct = c["surcharge_pct"]
                    base = round(cur_item["line_total"] / (1 + pct / 100), 2)
                    sur = round(cur_item["line_total"] - base, 2)
                    c["surcharge"] = sur
                    cur_item["surcharge"] = round(cur_item["surcharge"] + sur, 2)
                    cur_item["list_price"] = base
                    cur_item["unit_price"] = round(base / cur_item["qty"], 2)
                    cur_item["flags"].append(
                        f"sovrapprezzo colore {c['raw']} +{sur}€ (incorporato nel prezzo)")
                    # ricalcola il confronto col listino sul prezzo BASE (post-scorporo)
                    cur_item["flags"] = [f for f in cur_item["flags"] if "≠ listino" not in f]
                    std = comps.get(cur_item["comp_code"], {}).get("standard_price")
                    if std is not None and abs(float(std) - cur_item["unit_price"]) > 0.01:
                        cur_item["flags"].append(
                            f"prezzo {cur_item['unit_price']}€ ≠ listino {std}€")
        elif line.startswith(E_NUM) and cur_item is not None:
            cur_item["number_info"] = strip_lead_emoji(line)
        elif line.startswith(E_WARN) and cur_item is not None:
            note = strip_lead_emoji(line)
            cur_item["notes"].append(note)
            # Sovrapprezzo ESPLICITO "= N€": ricavo aggiuntivo, attribuito al
            # colore fuori catalogo della riga. unit_price resta il prezzo base.
            m = re.search(r"=\s*([\d.,]+)\s*€", note)
            if m and cur_item["line_total"] is not None:
                add = money(m.group(1))
                cur_item["surcharge"] = round(cur_item["surcharge"] + add, 2)
                cur_item["line_total"] = round(cur_item["line_total"] + add, 2)
                target = next((c for c in cur_item["colors"] if not c["in_catalog"]), None)
                if target is not None:
                    target["surcharge"] = round(target["surcharge"] + add, 2)
                    cur_item["flags"].append(
                        f"sovrapprezzo colore {target['raw']} +{add}€")
                else:
                    cur_item["flags"].append(
                        f"sovrapprezzo +{add}€ ma nessun colore fuori catalogo — verificare")
            else:
                cur_item["flags"].append(f"sovrapprezzo: {note}")
        elif line.startswith(E_GIFT) and cur_item is not None:
            cur_item["notes"].append("omaggio: " + strip_lead_emoji(line))
        elif line.startswith(E_MONEY) or line.startswith(E_TAG):
            money_lines.append(strip_lead_emoji(line))
            m = re.match(r"Tot\s+(\d{1,2}/\d{1,2})", strip_lead_emoji(line))

    # location validation + provenance + declared location total
    for key in order_seq:
        o = orders[key]
        loc = o["location"]
        if loc is None:
            o["location_status"] = "MANCANTE → DA DEFINIRE"
        elif loc.upper() in locations:
            o["location_status"] = "ok"
        elif loc.upper() == "IGLOO":
            o["location_status"] = "AMBIGUA (IGLOO SMALL o IGLOO BIG?)"
        else:
            o["location_status"] = "sconosciuta"
        o["gross_total"] = round(sum(i["line_total"] or 0 for i in o["items"]), 2)
        d = key[0][8:10] + "/" + key[0][5:7] if key[0] else "??"
        o["provenance"] = f"[import:{season} {month[:3]} d={d} loc={loc or 'NA'}]"

    return list(orders.values()), money_lines


def reconcile_days(orders, money_lines):
    """Confronta la somma delle righe per giorno col totale dichiarato 'Tot gg/mm'."""
    day_declared = {}
    for ml in money_lines:
        m = re.search(r"(\d{1,2}/\d{1,2}).{0,4}?:?\s*([\d.,]+)\s*€", ml)
        if m and ("tot" in ml.lower()):
            day_declared.setdefault(m.group(1), money(m.group(2)))
    day_computed = {}
    for o in orders:
        if not o["date"]:
            continue
        dd = o["date"][8:10] + "/" + o["date"][5:7]
        day_computed[dd] = round(day_computed.get(dd, 0) + o["gross_total"], 2)
    rows = []
    for dd in sorted(set(day_declared) | set(day_computed),
                     key=lambda x: (int(x.split("/")[1]), int(x.split("/")[0]))):
        comp = day_computed.get(dd)
        decl = day_declared.get(dd)
        ok = comp is not None and decl is not None and abs(comp - decl) < 0.01
        rows.append((dd, comp, decl, ok))
    return rows


def write_outputs(out_dir, month, orders, money_lines):
    out_dir.mkdir(parents=True, exist_ok=True)
    # items csv
    with (out_dir / f"items_{month}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["data", "location", "location_status", "comp_code", "comp_name",
                    "qty", "unit_price_base", "discount_%", "color_surcharge",
                    "line_total_lordo", "line_total_netto", "colori", "numero",
                    "note", "flags"])
        for o in orders:
            for it in o["items"]:
                cols = "; ".join(
                    f"{c['code'] or '?'}={c['raw']}"
                    + (f" [FC +{c['surcharge']}€]" if not c["in_catalog"] else "")
                    for c in it["colors"])
                net = round((it["line_total"] or 0) * (1 - it["discount"] / 100), 2)
                w.writerow([o["date"], o["location"], o["location_status"],
                            it["comp_code"], it["comp_name"], it["qty"],
                            it["unit_price"], it["discount"], it["surcharge"],
                            it["line_total"], net, cols,
                            it["number_info"] or "", " | ".join(it["notes"]),
                            " | ".join(it["flags"])])
    # orders csv
    with (out_dir / f"orders_{month}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["data", "location", "location_status", "n_items",
                    "totale_lordo", "sconto_%", "totale_netto", "provenance"])
        for o in orders:
            net = round(o["gross_total"] * (1 - DEFAULT_DISCOUNT / 100), 2)
            w.writerow([o["date"], o["location"], o["location_status"],
                        len(o["items"]), o["gross_total"], DEFAULT_DISCOUNT, net,
                        o["provenance"]])
    # json (ready to insert)
    (out_dir / f"{month}.json").write_text(
        json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8")
    return reconcile_days(orders, money_lines)


def write_report(out_dir, season, month, orders, recon):
    n_items = sum(len(o["items"]) for o in orders)
    gross = round(sum(o["gross_total"] for o in orders), 2)
    net = round(gross * (1 - 10 / 100), 2)
    surch = round(sum(c["surcharge"] for o in orders for it in o["items"]
                      for c in it["colors"]), 2)
    L = [f"# Report parsing — {season} / {month}", "",
         f"- Ordini (giorno+location): **{len(orders)}**",
         f"- Voci (order_item): **{n_items}**",
         f"- Ricavo lordo totale: **€ {gross}**",
         f"- Ricavo netto (sconto 10% su tutti gli ordini): **€ {net}**",
         f"- di cui sovrapprezzi colore fuori catalogo: **€ {surch}** lordi "
         f"(€ {round(surch * 0.9, 2)} netti)", "",
         "## Cross-check totali giornalieri (righe vs 'Tot gg/mm' del file)", "",
         "| Giorno | Somma righe | Totale dichiarato | OK |",
         "|---|--:|--:|:-:|"]
    for dd, comp, decl, ok in recon:
        L.append(f"| {dd} | {comp} | {decl} | {'✅' if ok else '❌'} |")

    L += ["", "## Incongruenze e decisioni da prendere", ""]
    # location issues
    locbad = [o for o in orders if o["location_status"] != "ok"]
    L.append(f"### Location non ok ({len(locbad)})")
    L.append("| Data | Location | Stato |")
    L.append("|---|---|---|")
    for o in locbad:
        L.append(f"| {o['date']} | {o['location'] or '—'} | {o['location_status']} |")
    # item flags
    flagged = [(o, it) for o in orders for it in o["items"] if it["flags"]]
    L += ["", f"### Voci con segnalazioni ({len(flagged)})",
          "| Data | Location | Voce | Flag |", "|---|---|---|---|"]
    for o, it in flagged:
        L.append(f"| {o['date']} | {o['location'] or '—'} | {it['raw']} | "
                 f"{' ; '.join(it['flags'])} |")
    # off-catalog colors (attesi, con sovrapprezzo) — informativo
    fc = [(o, it, c) for o in orders for it in o["items"]
          for c in it["colors"] if c["status"] == "fuori catalogo"]
    L += ["", f"### Colori fuori catalogo usati ({len(fc)}) — attesi, con sovrapprezzo",
          "| Data | Location | Voce | Colore | Sovrapprezzo € |", "|---|---|---|---|--:|"]
    for o, it, c in fc:
        L.append(f"| {o['date']} | {o['location'] or '—'} | {it['comp_name']} | "
                 f"{c['code']} {c['raw']} | {c['surcharge']} |")
    # truly unknown colors — da mappare
    unk = [(o, it, c) for o in orders for it in o["items"]
           for c in it["colors"] if c["status"] == "SCONOSCIUTO"]
    L += ["", f"### Colori sconosciuti da mappare ({len(unk)})",
          "| Data | Location | Voce | Colore |", "|---|---|---|---|"]
    for o, it, c in unk:
        L.append(f"| {o['date']} | {o['location'] or '—'} | {it['comp_name']} | {c['raw']} |")

    (out_dir / f"report_{month}.md").write_text("\n".join(L), encoding="utf-8")


def main():
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-2027"
    month = (sys.argv[2] if len(sys.argv) > 2 else "september").lower()
    src = ROOT / "data" / season / f"{month}.txt"
    out_dir = ROOT / "data" / "import_review" / season
    orders, money_lines = parse_file(src, season, month)
    recon = write_outputs(out_dir, month, orders, money_lines)
    write_report(out_dir, season, month, orders, recon)
    print(f"{season}/{month}: {len(orders)} ordini, "
          f"{sum(len(o['items']) for o in orders)} voci. Output in {out_dir}")


if __name__ == "__main__":
    main()
