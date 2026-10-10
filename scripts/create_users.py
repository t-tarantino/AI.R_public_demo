"""Create or update web-app user accounts.

Usage (from the project root, venv active):

    python -m scripts.create_users                 # seed default worker accounts
    python -m scripts.create_users NAME PASSWORD          # editor account
    python -m scripts.create_users NAME PASSWORD admin    # ... as an admin
    python -m scripts.create_users NAME PASSWORD viewer   # ... read-only

Default seed: one account per worker party (AL, BO, CA, DA), username =
lowercase nickname, password = 'demo1234' (to be changed!). AL is admin.
"""
from __future__ import annotations

import sys

from app.db.models import Party, User
from app.db.session import SessionLocal
from app.services.security import hash_password

DEFAULT_PASSWORD = "demo1234"


def upsert(db, username: str, password: str, party_id: int | None = None,
           is_admin: bool = False, can_edit: bool = True) -> str:
    tag = " (admin)" if is_admin else ("" if can_edit else " (sola lettura)")
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        db.add(User(username=username, password_hash=hash_password(password),
                    party_id=party_id, is_admin=is_admin, can_edit=can_edit))
        return f"creato   {username}" + tag
    user.password_hash = hash_password(password)
    user.active = True
    user.can_edit = can_edit
    if is_admin:
        user.is_admin = True
    return f"aggiornato {username}" + tag


def main() -> None:
    db = SessionLocal()
    try:
        if len(sys.argv) in (3, 4):
            role = sys.argv[3].lower() if len(sys.argv) == 4 else ""
            is_admin = role == "admin"
            can_edit = role != "viewer"
            print(upsert(db, sys.argv[1], sys.argv[2],
                         is_admin=is_admin, can_edit=can_edit))
        else:
            workers = db.query(Party).filter(Party.is_worker.is_(True)).all()
            for p in workers:
                username = (p.code_nickname or p.name).lower()
                print(upsert(db, username, DEFAULT_PASSWORD, party_id=p.party_id,
                             is_admin=(p.code_nickname == "AL")))
            print(f"\nPassword iniziale per tutti: '{DEFAULT_PASSWORD}' — da cambiare!")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()