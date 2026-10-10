"""Shared helpers for the Richie batch importers (orders and expenses)."""
from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Color, Party

CENTS = Decimal("0.01")
RICHIE_MARKER = "[richie]"   # provenance marker appended to every imported row's comment


def q(x) -> Decimal:
    return Decimal(x or 0).quantize(CENTS)


def commit_comment(original: str | None, status: str, messages: list[str]) -> str:
    """Comment stored on an imported row: the original note + the [richie] marker,
    and — for a `doubt` row — the doubt reasons, so the uncertainty travels with
    the created record and a human can find and fix it later."""
    base = (original + " " if original else "") + RICHIE_MARKER
    if status == "doubt" and messages:
        base += " · dubbi: " + "; ".join(messages)
    return base


def parse_date(s: str | None, today: date | None = None) -> date | None:
    s = (s or "").strip()
    today = today or date.today()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    for fmt in ("%d/%m", "%d-%m"):
        try:
            return datetime.strptime(f"{s}/{today.year}", fmt + "/%Y").date()
        except ValueError:
            pass
    return None


def fmt_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def parse_time(s: str | None) -> time | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%H:%M", "%H.%M", "%H", "%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


class ColorResolver:
    """Resolve a written colour code: exact (case-insensitive); a bare number
    also matches its zero-padded form ('45' -> '045')."""

    def __init__(self, db: Session):
        self.by_code = {c.code.strip().lower(): c for c in db.query(Color).all()}

    def resolve(self, code: str | None) -> Color | None:
        key = (code or "").strip().lower()
        if not key:
            return None
        c = self.by_code.get(key)
        if c is None and key.isdigit():
            c = self.by_code.get(f"{int(key):03d}")
        return c

    def resolve_checked(self, code: str | None, name: str | None):
        """Resolve by CODE and verify the NAME matches, to avoid colour ambiguity.

        Returns (color, problem) where problem is None | 'missing' (no code) |
        'unknown' (code not found) | 'missing_name' (code ok, name empty) |
        'mismatch' (name does not match the code's colour)."""
        c = self.resolve(code)
        if not (code or "").strip():
            return None, "missing"
        if c is None:
            return None, "unknown"
        given = (name or "").strip().lower()
        if not given:
            return c, "missing_name"
        if given != c.name.strip().lower():
            return c, "mismatch"
        return c, None


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-zàèéìòùü0-9]+", (s or "").lower()) if len(t) >= 3]


class PartyResolver:
    """Resolve a written party reference: first by code (sigla), then by name.

    Matching is case-insensitive and exact. Returns (party, problem) where
    problem is None, 'missing', 'unknown' or 'ambiguous'.
    """

    def __init__(self, db: Session):
        self.by_code: dict[str, Party] = {}
        self.by_name: dict[str, list[Party]] = {}
        for p in db.query(Party).all():
            if p.code_nickname:
                self.by_code[p.code_nickname.strip().lower()] = p
            self.by_name.setdefault(p.name.strip().lower(), []).append(p)

    def resolve(self, written: str | None) -> tuple[Party | None, str | None]:
        key = (written or "").strip().lower()
        if not key:
            return None, "missing"
        if key in self.by_code:
            return self.by_code[key], None
        hits = self.by_name.get(key, [])
        if len(hits) == 1:
            return hits[0], None
        return None, "ambiguous" if hits else "unknown"


def tally(results) -> dict[str, int]:
    return {k: sum(1 for r in results if r.status == k)
            for k in ("ok", "doubt", "error", "duplicate")}
