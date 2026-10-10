"""FASE 1 (spese) — parsing del registro spese mensile.

Legge `data/<stagione>/expences_<mese>_<anno>.txt` (formato a blocchi separati da
righe di '='), estrae ogni ordine fornitore come una spesa con le sue righe, e:
- calcola il totale di ogni spesa come SOMMA DELLE SINGOLE VOCI (fonte di verita');
- deduplica i PRODOTTI (per fornitore-venditore + colore + taglia) proponendoli
  come SKU da aggiungere al master;
- fa il cross-check con i subtotali dichiarati nel file (segnala le differenze).

Produce in data/import_review/<stagione>/:
  * expenses_<mese>.json          (pronto per load_expenses.py)
  * expenses_<mese>.csv, expense_items_<mese>.csv
  * products_<mese>.toml          (blocchi [[product]] da incollare nel master)
  * report_expenses_<mese>.md

NON scrive nel DB.

    python -m scripts.extract_expenses 2026-2027 september
"""
from __future__ import annotations

import csv
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "master_data.toml"
OUT = ROOT / "data" / "import_review"

# vendor nel titolo -> code_nickname del fornitore (paid_to)
VENDOR_TO_SUPPLIER = {"AMAZON": "AMZ", "FESTIVAL": "FMG"}

PRICE_LABELS = [
    "Prezzo unitario mostrato", "Prezzo unitario",
    "Prezzo mostrato nella pagina prodotto", "Prezzo/parziale mostrato",
    "Prezzo attualmente mostrato", "Prezzo mostrato",
]


def money(s: str) -> float | None:
    m = re.search(r"[\d]+(?:[.,]\d+)?", s)
    return float(m.group(0).replace(".", "").replace(",", ".")) if m else None


def load_colors() -> dict[str, str]:
    with MASTER.open("rb") as fh:
        d = tomllib.load(fh)
    return {c["code"]: c["name"] for c in d.get("color", [])}


def required_item_for(name: str) -> tuple[str, str]:
    """Ritorna (required_item_name, size_label) dal testo dell'articolo."""
    low = name.lower()
    if '5"' in low or "12,5" in low or "12.5" in low:
        return "Palloncino piccolo", "12.5cm"
    return "Palloncino grande", "30cm"   # Amazon senza taglia -> 30cm (assunto)


def brand_token(name: str, seller: str | None) -> str:
    if name.lower().startswith("gemar"):
        return "Gemar"
    src = seller or name
    tok = re.sub(r"[^A-Za-z0-9]", " ", src).split()
    return (tok[0].title() if tok else "Sku")


def split_items(body: str) -> list[str]:
    """Divide il corpo del blocco nelle singole voci."""
    # voci numerate '1) ... 2) ...'
    parts = re.split(r"(?m)^\s*\d+\)\s*", body)
    items = [p for p in parts[1:] if p.strip()]
    if items:
        return items
    # blocco a voce singola: da 'Articolo:' in poi
    m = re.search(r"(?ms)^\s*Articolo:.*", body)
    return [m.group(0)] if m else []


def field(text: str, label: str) -> str | None:
    m = re.search(rf"{re.escape(label)}\s*:\s*(.+)", text)
    return m.group(1).strip() if m else None


def parse_item(chunk: str, block_seller: str | None):
    name = field(chunk, "Articolo")
    if not name:
        # voce numerata: il nome e' la prima riga del chunk
        name = chunk.strip().splitlines()[0].strip()
    cm = re.search(r"Codice colore:\s*(\d{3})", chunk)
    color = cm.group(1) if cm else None
    qm = re.search(r"Quantita'?:\s*(\d+)", chunk)
    qty = int(qm.group(1)) if qm else 1
    unit = None
    for lab in PRICE_LABELS:
        m = re.search(rf"{lab}\s*:\s*([0-9.,]+)\s*EUR", chunk)
        if m:
            unit = money(m.group(1))
            break
    seller = field(chunk, "Supplier") or block_seller
    req, size = required_item_for(name)
    return {"raw_name": name, "color_code": color, "quantity": qty,
            "unit_cost": unit, "seller": seller, "required_item": req, "size": size}


def parse(path: Path, season: str, month: str):
    text = path.read_text(encoding="utf-8")
    colors = load_colors()
    # blocchi: separati da righe di '='; alterna titolo/corpo
    chunks = [c.strip() for c in re.split(r"(?m)^=+\s*$", text)]
    expenses = []
    products: dict[str, dict] = {}
    i = 0
    while i < len(chunks):
        title = chunks[i]
        dm = re.match(r"(\d{2})/(\d{2})/(\d{4})", title)
        if not dm:
            i += 1
            continue
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        i += 2
        date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
        vendor = "FESTIVAL" if "FESTIVAL" in title.upper() else "AMAZON"
        supplier_code = VENDOR_TO_SUPPLIER[vendor]
        order_ref = field(body, "Ordine") or field(body, "Fattura")
        block_seller = field(body, "Supplier")
        file_subtotal = None
        for lab in ("Totale merce / imponibile registrato", "Subtotale articoli registrato",
                    "Subtotale registrato", "Subtotale articoli"):
            v = field(body, lab)
            if v:
                file_subtotal = money(v)
                break

        items = []
        for chunk in split_items(body):
            it = parse_item(chunk, block_seller)
            if it["unit_cost"] is None or it["color_code"] is None:
                continue
            brand = brand_token(it["raw_name"], it["seller"])
            pcode = f"{it['color_code']}-{re.sub(r'[^A-Za-z0-9]','',brand).upper()}-{'G' if it['size']=='30cm' else 'P'}"
            cname = colors.get(it["color_code"], "?")
            pname = f"{brand} {it['size']} {cname}"
            products.setdefault(pcode, {
                "product_code": pcode, "required_item_name": it["required_item"],
                "color_code": it["color_code"], "name": pname,
                "comment": f"Fornitore/venditore: {it['seller'] or vendor}"})
            it["product_code"] = pcode
            it["product_name"] = pname
            it["color_name"] = cname
            it["line_total"] = round(it["quantity"] * it["unit_cost"], 2)
            items.append(it)

        computed = round(sum(x["line_total"] for x in items), 2)
        d = f"{dm.group(1)}/{dm.group(2)}"
        expenses.append({
            "date": date, "vendor": vendor, "supplier_code": supplier_code,
            "order_ref": order_ref, "items": items,
            "file_subtotal": file_subtotal, "total_cost": computed,
            "provenance": f"[import:{season} exp {month[:3]} d={d} {vendor} {order_ref or ''}]".strip(),
        })
    return expenses, list(products.values())


def write(out_dir: Path, season: str, month: str, expenses, products):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"expenses_{month}.json").write_text(
        json.dumps(expenses, ensure_ascii=False, indent=2), encoding="utf-8")

    with (out_dir / f"expenses_{month}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["data", "fornitore", "ordine", "n_voci", "totale_voci",
                    "subtotale_file", "delta", "provenance"])
        for e in expenses:
            delta = None if e["file_subtotal"] is None else round(e["total_cost"] - e["file_subtotal"], 2)
            w.writerow([e["date"], e["supplier_code"], e["order_ref"], len(e["items"]),
                        e["total_cost"], e["file_subtotal"], delta, e["provenance"]])

    with (out_dir / f"expense_items_{month}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["data", "fornitore", "articolo", "colore", "qta", "prezzo_unit",
                    "totale_riga", "product_code", "required_item", "venditore"])
        for e in expenses:
            for it in e["items"]:
                w.writerow([e["date"], e["supplier_code"], it["raw_name"],
                            f"{it['color_code']} {it['color_name']}", it["quantity"],
                            it["unit_cost"], it["line_total"], it["product_code"],
                            it["required_item"], it["seller"]])

    # TOML dei prodotti da incollare nel master
    lines = ["# Prodotti generati da expences (rivedere e incollare in master_data.toml)"]
    for p in sorted(products, key=lambda x: x["product_code"]):
        lines += ["[[product]]",
                  f'product_code       = "{p["product_code"]}"',
                  f'required_item_name = "{p["required_item_name"]}"',
                  f'color_code         = "{p["color_code"]}"',
                  f'name               = "{p["name"]}"',
                  f'product_link       = ""',
                  f'comment            = "{p["comment"]}"', ""]
    (out_dir / f"products_{month}.toml").write_text("\n".join(lines), encoding="utf-8")

    # report
    tot = round(sum(e["total_cost"] for e in expenses), 2)
    file_tot = round(sum(e["file_subtotal"] for e in expenses if e["file_subtotal"] is not None), 2)
    L = [f"# Report spese — {season} / {month}", "",
         f"- Spese (ordini fornitore): **{len(expenses)}**",
         f"- Prodotti distinti proposti: **{len(products)}**",
         f"- Totale (somma voci = verita'): **€ {tot}**",
         f"- Totale subtotali dichiarati nel file: **€ {file_tot}**", "",
         "## Cross-check per ordine (somma voci vs subtotale del file)", "",
         "| Data | Fornitore | Somma voci | Subtotale file | Δ |", "|---|---|--:|--:|--:|"]
    for e in expenses:
        delta = "" if e["file_subtotal"] is None else round(e["total_cost"] - e["file_subtotal"], 2)
        flag = "" if (e["file_subtotal"] is None or abs(e["total_cost"]-e["file_subtotal"])<0.01) else " ⚠️"
        L.append(f"| {e['date']} | {e['supplier_code']} | {e['total_cost']} | "
                 f"{e['file_subtotal']} | {delta}{flag} |")
    (out_dir / f"report_expenses_{month}.md").write_text("\n".join(L), encoding="utf-8")


def main():
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-2027"
    month = (sys.argv[2] if len(sys.argv) > 2 else "september").lower()
    # il file usa 'expences_settember_2026.txt'
    candidates = list((ROOT / "data" / season).glob("expences_*"))
    src = candidates[0] if candidates else (ROOT / "data" / season / f"expences_{month}.txt")
    expenses, products = parse(src, season, month)
    out_dir = OUT / season
    write(out_dir, season, month, expenses, products)
    print(f"{season}/{month}: {len(expenses)} spese, "
          f"{sum(len(e['items']) for e in expenses)} voci, {len(products)} prodotti. "
          f"Fonte: {src.name}")


if __name__ == "__main__":
    main()
