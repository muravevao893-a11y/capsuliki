from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def _engine_kwargs() -> dict:
    if settings.is_sqlite:
        return {"connect_args": {"check_same_thread": False}, "pool_pre_ping": True}
    if settings.is_postgres:
        return {
            "pool_pre_ping": True,
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_recycle": settings.db_pool_recycle_seconds,
            "connect_args": {"connect_timeout": 10},
        }
    return {"pool_pre_ping": True}


engine = create_engine(settings.database_url, future=True, echo=settings.db_echo, **_engine_kwargs())

if settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def database_status() -> dict[str, str]:
    return {
        "kind": settings.database_kind,
        "url": settings.safe_database_url,
        "driver": engine.url.drivername,
    }


def ping_database() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns(table)}
    if column in existing:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _create_index_if_missing(name: str, ddl: str) -> None:
    with engine.begin() as conn:
        try:
            conn.execute(text(ddl))
        except Exception:
            # Some DBs return index-exists or table-not-ready. Early MVP keeps this soft.
            pass


def run_light_migrations() -> None:
    inspector = inspect(engine)
    if "players" not in inspector.get_table_names():
        return
    _add_column_if_missing("players", "capsule_dust", "capsule_dust INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("players", "season_score", "season_score INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("players", "banned_at", "banned_at TIMESTAMP")
    _add_column_if_missing("players", "ban_reason", "ban_reason TEXT")
    _add_column_if_missing("players", "is_banned", "is_banned INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("players", "referrals_count", "referrals_count INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("players", "referrer_player_id", "referrer_player_id INTEGER")
    _create_index_if_missing("ix_players_tg", "CREATE INDEX IF NOT EXISTS ix_players_tg ON players (telegram_user_id)")
    _create_index_if_missing("ix_players_referrer", "CREATE INDEX IF NOT EXISTS ix_players_referrer ON players (referrer_player_id)")
    _create_index_if_missing("ix_players_season_score", "CREATE INDEX IF NOT EXISTS ix_players_season_score ON players (season_score)")
    _create_index_if_missing("ix_players_banned", "CREATE INDEX IF NOT EXISTS ix_players_banned ON players (is_banned)")
    _create_index_if_missing("ix_pets_owner", "CREATE INDEX IF NOT EXISTS ix_pets_owner ON pets (owner_player_id)")
    _create_index_if_missing("ix_events_chat", "CREATE INDEX IF NOT EXISTS ix_group_events_chat ON group_events (chat_id, status)")
    _create_index_if_missing("ix_logs_created", "CREATE INDEX IF NOT EXISTS ix_action_logs_created ON action_logs (created_at)")
    _create_index_if_missing("ix_group_chats_status_last_event", "CREATE INDEX IF NOT EXISTS ix_group_chats_status_last_event ON group_chats (status, last_event_at)")
    _create_index_if_missing("ix_error_logs_created", "CREATE INDEX IF NOT EXISTS ix_error_logs_created ON error_logs (created_at)")
    _create_index_if_missing("ix_error_logs_chat_created", "CREATE INDEX IF NOT EXISTS ix_error_logs_chat_created ON error_logs (chat_id, created_at)")
    _create_index_if_missing("ix_star_purchases_payload", "CREATE INDEX IF NOT EXISTS ix_star_purchases_payload ON star_purchases (payload)")
    _create_index_if_missing("ix_star_purchases_player_created", "CREATE INDEX IF NOT EXISTS ix_star_purchases_player_created ON star_purchases (player_id, created_at)")


def record_schema_version(version: str = "1.0") -> None:
    from app.models import SchemaVersion

    session = SessionLocal()
    try:
        exists = session.query(SchemaVersion).filter(SchemaVersion.version == version).first()
        if not exists:
            session.add(SchemaVersion(version=version))
            session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def init_db() -> None:
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    run_light_migrations()
    record_schema_version("1.0")
    record_schema_version("1.1")


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
