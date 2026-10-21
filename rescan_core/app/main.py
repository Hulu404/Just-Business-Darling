"""Сборка FastAPI-приложения rescan_core.

Запуск: uvicorn app.main:app --reload
Документация: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import api_router
from app.config import get_settings
from app.db.session import engine

settings = get_settings()
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Проверяем доступность БД на старте — падать сразу, а не на первом запросе.
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - диагностика окружения
        logging.getLogger("rescan").error(
            "Нет соединения с базой. Проверь DATABASE_URL и что PostgreSQL запущен: %s", exc
        )
    yield


app = FastAPI(
    title="rescan_core",
    version="0.2.0",
    description="Ядро rescan: каркас B1 (PostgreSQL, миграции, роли, аудит) и приём событий B2.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["system"], summary="Проверка живости")
def health() -> dict:
    """Liveness + проверка БД. Оркестратор стучит сюда на хосте в РФ."""
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "version": app.version,
        "environment": settings.environment,
        "database": "ok" if db_ok else "unavailable",
    }
