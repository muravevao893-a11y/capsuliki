from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.config import get_settings
from app.db import database_status, engine
from app.redis_store import redis_configured, redis_ping

router = APIRouter(prefix="/api")


def _redis_state() -> str:
    if not redis_configured():
        return "disabled"
    return "ok" if redis_ping() else "error"


@router.get("/health")
async def health() -> dict:
    db = database_status()
    return {
        "status": "ok",
        "service": "capsuliki-bot",
        "database": {"kind": db["kind"], "driver": db["driver"]},
        "redis": _redis_state(),
    }


@router.get("/ready")
async def ready() -> dict:
    settings = get_settings()
    db = database_status()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    redis_state = _redis_state()
    if settings.redis_required and redis_state != "ok":
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "database": "ok", "database_info": db, "redis": redis_state},
        )
    return {"status": "ready", "database": "ok", "database_info": db, "redis": redis_state}
