"""Sincronizza il master data (schema v2) da data/master_data.toml nel database.

MODALITÀ UPSERT (non distruttiva): aggiorna in-place le righe master esistenti
(mantenendo gli ID, quindi le chiavi esterne delle transazioni restano valide),
inserisce quelle nuove e NON tocca mai le tabelle transazionali (ordini, ore,
spese, movimenti di magazzino) né gli account/audit.

    python -m scripts.import_data

- Entità referenziate dalle transazioni (color, composition, location, party,
  expense_category, required_item, product) → UPSERT per chiave naturale.
- Tabelle solo-master senza FK transazionali (requirements, stock_threshold)
  → ricostruite (delete+insert): è sicuro perché nessuna transazione le referenzia.
- Righe presenti nel DB ma assenti dal file → segnalate (NON eliminate) per non
  rompere lo storico. Vanno eventualmente ritirate a mano (`active = false`).
"""
from __future__ import annotations

import tomllib
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.db.models import (
    Color,
    Composition,
    ExpenseCategory,
    Location,
    Party,
    Product,
    RequiredItem,
    Requirement,
    StockThreshold,
    User,
)
from app.db.session import SessionLocal

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "master_data.toml"


# --- helpers: "" -> NULL e cast tipizzati ------------------------------------
def _text(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _decimal(value, field: str) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - user input guard
        raise ValueError(f"Valore numerico non valido in '{field}': {value!r}") from exc


def _int(value, field: str) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:  # pragma: no cover - user input guard
        raise ValueError(f"Valore intero non valido in '{field}': {value!r}") from exc


def _bool(value, default: bool = False) -> bool:
    text = _text(value)
    if text is None:
        return default
    return text.lower() in {"true", "1", "yes", "si", "sì"}


class Stats:
    def __init__(self):
        self.ins = 0
        self.upd = 0

    def bump(self, created: bool):
        if created:
            self.ins += 1
        else:
            self.upd += 1

    def __str__(self):
        return f"{self.ins} nuovi, {self.upd} aggiornati"


def upsert(db, model, key: dict, values: dict, stats: Stats):
    """Trova per chiave naturale e aggiorna, oppure crea. Ritorna l'oggetto."""
    obj = db.query(model).filter_by(**key).one_or_none()
    if obj is None:
        obj = model(**{**key, **values})   # values override key on overlap
        db.add(obj)
        stats.bump(True)
    else:
        for field, val in values.items():
            setattr(obj, field, val)
        stats.bump(False)
    return obj


def warn_extras(db, model, key_field: str, present_keys: set, label: str, warnings: list):
    """Segnala righe nel DB la cui chiave non è più nel file (non le elimina)."""
    for obj in db.query(model).all():
        k = getattr(obj, key_field)
        if k is not None and k not in present_keys:
            warnings.append(f"{label}: '{k}' presente nel DB ma non nel file "
                            f"(non eliminato; ritirare a mano se serve).")


def relink_users(db) -> None:
    """Collega gli account senza party al worker con nickname corrispondente."""
    parties = {p.code_nickname.lower(): p.party_id
               for p in db.query(Party).filter(Party.code_nickname.isnot(None))}
    for user in db.query(User).filter(User.party_id.is_(None)):
        user.party_id = parties.get(user.username)


def load() -> None:
    with DATA_FILE.open("rb") as fh:
        data = tomllib.load(fh)

    db = SessionLocal()
    try:
        warnings: list[str] = []

        # --- expense_category (lista di nomi) -------------------------------
        cat_stats = Stats()
        for name in data.get("expense_category", []):
            upsert(db, ExpenseCategory, {"name": name}, {}, cat_stats)
        warn_extras(db, ExpenseCategory, "name",
                    set(data.get("expense_category", [])), "expense_category", warnings)

        # --- color ----------------------------------------------------------
        color_stats = Stats()
        colors: dict[str, Color] = {}
        for r in data.get("color", []):
            colors[r["code"]] = upsert(db, Color, {"code": r["code"]}, {
                "name": r["name"], "type": _text(r.get("type")),
                "active": _bool(r.get("active"), default=True),
                "in_catalog": _bool(r.get("in_catalog"), default=True),
                "comment": _text(r.get("comment"))}, color_stats)
        warn_extras(db, Color, "code", set(colors), "color", warnings)

        # --- location -------------------------------------------------------
        loc_stats = Stats()
        for r in data.get("location", []):
            upsert(db, Location, {"name": r["name"]}, {
                "address": _text(r.get("address")), "phone": _text(r.get("phone")),
                "email": _text(r.get("email")), "comment": _text(r.get("comment"))}, loc_stats)
        warn_extras(db, Location, "name",
                    {r["name"] for r in data.get("location", [])}, "location", warnings)

        # --- party (chiave: code_nickname se presente, altrimenti name) -----
        party_stats = Stats()
        for r in data.get("party", []):
            nick = _text(r.get("code_nickname"))
            key = {"code_nickname": nick} if nick else {"name": r["name"]}
            upsert(db, Party, key, {
                "name": r["name"], "code_nickname": nick,
                "is_customer": _bool(r.get("is_customer")),
                "is_supplier": _bool(r.get("is_supplier")),
                "is_worker": _bool(r.get("is_worker")),
                "is_business": _bool(r.get("is_business")),
                "category": _text(r.get("category")), "phone": _text(r.get("phone")),
                "email": _text(r.get("email")), "website": _text(r.get("website")),
                "comment": _text(r.get("comment"))}, party_stats)

        # --- composition ----------------------------------------------------
        comp_stats = Stats()
        compositions: dict[str, Composition] = {}
        for r in data.get("composition", []):
            compositions[r["code"]] = upsert(db, Composition, {"code": r["code"]}, {
                "name": r["name"],
                "standard_price": _decimal(r["standard_price"], f"composition {r['code']}"),
                "estimated_working_time": _int(r.get("estimated_working_time"),
                                               f"composition {r['code']}"),
                "active": _bool(r.get("active"), default=True),
                "comment": _text(r.get("comment"))}, comp_stats)
        warn_extras(db, Composition, "code", set(compositions), "composition", warnings)

        # --- required_item --------------------------------------------------
        item_stats = Stats()
        required_items: dict[str, RequiredItem] = {}
        for r in data.get("required_item", []):
            # Number materials are flagged explicitly in the file, else inferred
            # from the name ("Palloncino numero ...").
            raw_is_number = r.get("is_number")
            is_number = (_bool(raw_is_number) if raw_is_number is not None
                         else r["name"].lower().startswith("palloncino numero"))
            required_items[r["name"]] = upsert(db, RequiredItem, {"name": r["name"]}, {
                "type": _text(r.get("type")), "dimension": _text(r.get("dimension")),
                "unit": _text(r.get("unit")) or "piece", "used_color": _bool(r.get("used_color")),
                "is_number": is_number,
                "minimum_safe_quantity": _int(r.get("minimum_safe_quantity"),
                                              f"required_item {r['name']}"),
                "comment": _text(r.get("comment"))}, item_stats)
        warn_extras(db, RequiredItem, "name", set(required_items), "required_item", warnings)

        db.flush()  # assicura gli ID per FK e per le ricostruzioni sotto

        # --- requirements (SOLO master → ricostruzione sicura) --------------
        db.query(Requirement).delete()
        n_req = 0
        for r in data.get("requirement", []):
            comp = compositions.get(r["composition_code"])
            item = required_items.get(r["required_item_name"])
            if comp is None:
                raise ValueError(f"requirement: composition_code {r['composition_code']!r} inesistente.")
            if item is None:
                raise ValueError(f"requirement: required_item_name {r['required_item_name']!r} inesistente.")
            db.add(Requirement(composition=comp, required_item=item,
                               quantity=_decimal(r["quantity"], "requirement.quantity"),
                               comment=_text(r.get("comment"))))
            n_req += 1

        # --- stock_threshold (SOLO master → ricostruzione sicura) -----------
        db.query(StockThreshold).delete()
        n_thr = 0
        for r in data.get("stock_threshold", []):
            item = required_items.get(r["required_item_name"])
            if item is None:
                raise ValueError(f"stock_threshold: required_item_name "
                                 f"{r['required_item_name']!r} inesistente.")
            color = None
            color_code = _text(r.get("color_code"))
            if color_code is not None:
                color = colors.get(color_code)
                if color is None:
                    raise ValueError(f"stock_threshold: color_code {color_code!r} inesistente.")
            db.add(StockThreshold(
                required_item=item, color=color, variant=_text(r.get("variant")),
                minimum_quantity=_int(r["minimum_quantity"], "stock_threshold.minimum_quantity"),
                comment=_text(r.get("comment"))))
            n_thr += 1


        # --- product (UPSERT: referenziato da expense_item) -----------------
        prod_stats = Stats()
        for r in data.get("product", []):
            item = required_items.get(r["required_item_name"])
            if item is None:
                raise ValueError(f"product {r.get('name')!r}: required_item_name "
                                 f"{r['required_item_name']!r} inesistente.")
            color = None
            color_code = _text(r.get("color_code"))
            if color_code is not None:
                color = colors.get(color_code)
                if color is None:
                    raise ValueError(f"product {r.get('name')!r}: color_code {color_code!r} inesistente.")
            code = _text(r.get("product_code"))
            key = {"product_code": code} if code else {"name": r["name"]}
            # Pack size (pieces per purchased unit): explicit in the file, else a
            # sensible default per material (balloons come in packs of 100).
            default_pack = 100 if item.name in {
                "Palloncino grande", "Palloncino piccolo", "Palloncino lungo"} else 1
            raw_pack = _text(r.get("package_quantity"))
            pack = int(raw_pack) if raw_pack is not None else default_pack
            upsert(db, Product, key, {
                "required_item": item, "color": color, "product_link": _text(r.get("product_link")),
                "name": r["name"], "package_quantity": pack,
                "active": _bool(r.get("active"), default=True),
                "comment": _text(r.get("comment"))}, prod_stats)

        relink_users(db)
        db.commit()

        print(f"Sincronizzato da {DATA_FILE.name} (UPSERT, transazioni intatte):")
        print(f"  categorie spese: {cat_stats} · colori: {color_stats} · location: {loc_stats}")
        print(f"  party: {party_stats} · composizioni: {comp_stats} · required_item: {item_stats}")
        print(f"  product: {prod_stats} · requirements ricostruiti: {n_req} · soglie: {n_thr}")
        if warnings:
            print(f"  Avvisi ({len(warnings)}):")
            for w in warnings:
                print("   -", w)
    finally:
        db.close()


if __name__ == "__main__":
    load()
