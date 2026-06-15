from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, database_status, engine, init_db
from app.models import Player, GroupEvent
from sqlalchemy import select, func


def main() -> int:
    settings = get_settings()
    info = database_status()
    print("Capsuliki database check")
    print(f"kind:   {info['kind']}")
    print(f"driver: {info['driver']}")
    print(f"url:    {info['url']}")

    if settings.is_sqlite:
        print("WARNING: сейчас используется SQLite. Для Railway/Postgres проверь DATABASE_URL.")

    init_db()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    with SessionLocal() as db:
        players = int(db.scalar(select(func.count(Player.id))) or 0)
        events = int(db.scalar(select(func.count(GroupEvent.id))) or 0)

    print("connection: ok")
    print(f"players: {players}")
    print(f"group_events: {events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
