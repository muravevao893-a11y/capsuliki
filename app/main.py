from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.bot import run_bot_polling
from app.config import get_settings
from app.db import database_status, init_db
from app.web import router as api_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
_bot_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot_task
    settings = get_settings()
    logger.info("Starting Capsuliki service: host=%s port=%s polling=%s", settings.host, settings.port, settings.run_bot_polling)
    logger.info("Database config: %s", database_status())
    init_db()
    logger.info("Database initialized")

    if settings.run_bot_polling and settings.has_bot_token:
        _bot_task = asyncio.create_task(run_bot_polling())
        logger.info("Telegram polling started")
    elif settings.run_bot_polling:
        logger.warning("RUN_BOT_POLLING=true, but BOT_TOKEN is empty/placeholder. Web server will run without bot polling.")

    yield

    if _bot_task:
        _bot_task.cancel()
        try:
            await _bot_task
        except asyncio.CancelledError:
            logger.info("Telegram polling stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Капсулики Bot", description="Telegram capsule-pet collection game bot.", version="1.3-postgres", lifespan=lifespan)
    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=int(os.getenv("PORT", settings.port)), reload=False)
