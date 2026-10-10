"""Application configuration loaded from environment variables / .env file."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object.

    Values are read from environment variables, falling back to a local `.env`
    file (see `.env.example`). Keeping this in one place means the only thing
    that changes when we move from SQLite to PostgreSQL is `DATABASE_URL`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./air.db"
    sql_echo: bool = False
    app_name: str = "AI.R public demo"
    app_env: str = "development"
    # Secret used to sign session cookies. Override in .env for production.
    secret_key: str = "dev-secret-change-me"
    # Mark session cookies `Secure` (sent only over HTTPS). Must be True in
    # production behind HTTPS; kept False for local http://localhost dev.
    cookie_secure: bool = False


settings = Settings()
