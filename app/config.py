from __future__ import annotations

from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    admin_ids: list[int] = Field(default_factory=list, alias="ADMIN_IDS")

    database_url: str = Field(default="sqlite:///./capsuliki.db", alias="DATABASE_URL")
    run_bot_polling: bool = Field(default=True, alias="RUN_BOT_POLLING")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8080, alias="PORT")
    app_secret: str = Field(default="change_me_please_32_chars_minimum", alias="APP_SECRET")

    enable_group_events: bool = Field(default=True, alias="ENABLE_GROUP_EVENTS")
    group_event_interval_minutes: int = Field(default=45, alias="GROUP_EVENT_INTERVAL_MINUTES")
    group_boss_interval_hours: int = Field(default=24, alias="GROUP_BOSS_INTERVAL_HOURS")

    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_recycle_seconds: int = Field(default=1800, alias="DB_POOL_RECYCLE_SECONDS")

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

    @property
    def has_bot_token(self) -> bool:
        return bool(self.bot_token and "PASTE_" not in self.bot_token and self.bot_token != "BOT_TOKEN")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
