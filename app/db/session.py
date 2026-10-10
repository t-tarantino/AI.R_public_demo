"""Database engine and session management."""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# Project root = ai-r/ (this file is app/db/session.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _normalize_sqlite_url(url: str) -> str:
    """Anchor a RELATIVE sqlite path to the project root.

    `sqlite:///./air.db` otherwise depends on the process working directory, so
    launching the app from a different folder would silently open a *different*
    (empty) database. Rewriting to an absolute path makes the app and the CLI
    scripts always use the same file. Non-sqlite / already-absolute URLs are
    returned unchanged.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    path = url[len(prefix):]
    if Path(path).is_absolute():
        return url
    return prefix + (PROJECT_ROOT / path).resolve().as_posix()


def _make_engine(url: str, echo: bool) -> Engine:
    """Create an Engine, applying SQLite-specific tweaks when relevant.

    On SQLite we enable enforcement of foreign-key constraints (off by default
    in SQLite) so that referential integrity behaves like PostgreSQL during the
    bootstrap phase. `check_same_thread=False` lets the connection be shared
    across FastAPI's threadpool.
    """
    url = _normalize_sqlite_url(url)
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _make_engine(settings.database_url, settings.sql_echo)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
