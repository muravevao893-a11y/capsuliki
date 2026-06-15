from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SQLITE_URL = "sqlite:///./capsuliki.db"
POSTGRES_ENV_FALLBACKS = (
    "DATABASE_PRIVATE_URL",
    "POSTGRES_URL",
    "POSTGRESQL_URL",
    "POSTGRES_DATABASE_URL",
)


def normalize_database_url(value: str | None) -> str:
    """Return a SQLAlchemy URL that works with the installed PostgreSQL driver.

    Railway/Postgres often exposes plain ``postgres://`` or ``postgresql://`` URLs.
    SQLAlchemy maps those to psycopg2 by default, while this project intentionally
    ships the modern psycopg v3 driver. Normalizing the scheme prevents the classic
    production crash: ``ModuleNotFoundError: No module named 'psycopg2'``.
    """
    raw = (value or "").strip()

    if raw in {"", "${{Postgres.DATABASE_URL}}", "${{POSTGRES.DATABASE_URL}}"}:
        for env_name in POSTGRES_ENV_FALLBACKS:
            candidate = os.getenv(env_name, "").strip()
            if candidate:
                raw = candidate
                break

    if not raw:
        raw = DEFAULT_SQLITE_URL

    if raw.startswith("postgres://"):
        return "postgresql+psycopg://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://"):]
    if raw.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + raw[len("postgresql+psycopg2://"):]
    return raw


def mask_database_url(value: str) -> str:
    """Mask credentials before logging or returning diagnostics."""
    try:
        parts = urlsplit(value)
    except Exception:
        return "invalid-url"

    if not parts.scheme:
        return "not-configured"
    if not parts.netloc:
        return parts.scheme

    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    username = parts.username or ""
    auth = f"{username}:***@" if username else ""
    return urlunsplit((parts.scheme, f"{auth}{host}{port}", parts.path, "", ""))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    admin_ids: list[int] = Field(default_factory=list, alias="ADMIN_IDS")

    database_url: str = Field(default=DEFAULT_SQLITE_URL, alias="DATABASE_URL")
    run_bot_polling: bool = Field(default=True, alias="RUN_BOT_POLLING")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8080, alias="PORT")
    app_secret: str = Field(default="change_me_please_32_chars_minimum", alias="APP_SECRET")

    redis_url: str = Field(default="", alias="REDIS_URL")
    redis_enabled: bool = Field(default=True, alias="REDIS_ENABLED")
    redis_required: bool = Field(default=False, alias="REDIS_REQUIRED")
    redis_socket_timeout_seconds: float = Field(default=2.0, alias="REDIS_SOCKET_TIMEOUT_SECONDS")

    enable_group_events: bool = Field(default=True, alias="ENABLE_GROUP_EVENTS")
    group_event_interval_minutes: int = Field(default=45, alias="GROUP_EVENT_INTERVAL_MINUTES")
    group_event_poll_seconds: int = Field(default=60, alias="GROUP_EVENT_POLL_SECONDS")
    group_event_batch_size: int = Field(default=10, alias="GROUP_EVENT_BATCH_SIZE")
    group_events_per_group: int = Field(default=2, alias="GROUP_EVENTS_PER_GROUP")
    group_event_lock_seconds: int = Field(default=120, alias="GROUP_EVENT_LOCK_SECONDS")
    group_boss_interval_hours: int = Field(default=24, alias="GROUP_BOSS_INTERVAL_HOURS")

    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_recycle_seconds: int = Field(default=1800, alias="DB_POOL_RECYCLE_SECONDS")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    stars_enabled: bool = Field(default=False, alias="STARS_ENABLED")
    stars_currency: str = Field(default="XTR", alias="STARS_CURRENCY")

    maintenance_mode: bool = Field(default=False, alias="MAINTENANCE_MODE")
    free_open_daily_limit: int = Field(default=1, alias="FREE_OPEN_DAILY_LIMIT")
    paid_open_daily_limit: int = Field(default=8, alias="PAID_OPEN_DAILY_LIMIT")
    care_daily_limit: int = Field(default=20, alias="CARE_DAILY_LIMIT")
    expedition_daily_limit: int = Field(default=5, alias="EXPEDITION_DAILY_LIMIT")
    group_catch_daily_limit: int = Field(default=10, alias="GROUP_CATCH_DAILY_LIMIT")

    admin_notify_payments: bool = Field(default=True, alias="ADMIN_NOTIFY_PAYMENTS")
    admin_notify_errors: bool = Field(default=False, alias="ADMIN_NOTIFY_ERRORS")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(x) for x in value]
        return [int(part.strip()) for part in str(value).replace(";", ",").split(",") if part.strip()]

    @model_validator(mode="after")
    def normalize_urls(self):
        self.database_url = normalize_database_url(self.database_url)
        self.redis_url = (self.redis_url or "").strip()
        return self

    @property
    def has_bot_token(self) -> bool:
        return bool(self.bot_token and "PASTE_" not in self.bot_token and self.bot_token != "BOT_TOKEN")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")

    @property
    def database_kind(self) -> str:
        if self.is_postgres:
            return "postgres"
        if self.is_sqlite:
            return "sqlite"
        return "other"

    @property
    def safe_database_url(self) -> str:
        return mask_database_url(self.database_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
