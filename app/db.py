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


engine = create_engine(settings.database_url, future=True, **_engine_kwargs())

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
    _create_index_if_missing("ix_players_tg", "CREATE INDEX IF NOT EXISTS ix_players_tg ON players (telegram_user_id)")
    _create_index_if_missing("ix_pets_owner", "CREATE INDEX IF NOT EXISTS ix_pets_owner ON pets (owner_player_id)")
    _create_index_if_missing("ix_events_chat", "CREATE INDEX IF NOT EXISTS ix_group_events_chat ON group_events (chat_id, status)")
    _create_index_if_missing("ix_logs_created", "CREATE INDEX IF NOT EXISTS ix_action_logs_created ON action_logs (created_at)")


def init_db() -> None:
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    run_light_migrations()


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
