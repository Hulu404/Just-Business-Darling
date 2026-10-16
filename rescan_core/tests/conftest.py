"""Общие фикстуры pytest.

Каждый тест получает СВОЮ чистую БД: отдельная SQLite-база в памяти через
StaticPool, схема создаётся из моделей (Base.metadata.create_all). Это быстро,
изолированно и не требует поднятого PostgreSQL при прогоне тестов.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ВАЖНО: импортируем модели ДО обращения к инстансу FastAPI, иначе имя пакета
# `app` и имя инстанса `app` конфликтуют между собой.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models import Clinic, Doctor, Format, Goal
from app.db.session import get_session
from app.main import app as fastapi_app
from app.security.hmac import compute_signature


@pytest.fixture
def db_session():
    """Чистая in-memory БД на тест + демо-клиника (приём событий без неё невозможен)."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    session = TestSession()
    clinic = Clinic(name="Тест-клиника", service_enabled=True)
    session.add(clinic)
    session.flush()
    session.add_all([
        Doctor(clinic_id=clinic.id, external_id="doc-1", full_name="Тестовый Врач"),
        Format(clinic_id=clinic.id, title="Приём", price_kopecks=100000),
        Goal(clinic_id=clinic.id, title="Цель", sort_order=1),
    ])
    session.commit()

    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    """TestClient, у которого зависимость get_session подменена на тестовую БД."""
    fastapi_app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def sign_headers():
    """Подписать тело тем же секретом, что в настройках (dev-only-change-me)."""

    def _make(body: bytes, secret: str = "dev-only-change-me", ts: int | None = None) -> dict:
        import time

        timestamp = str(ts if ts is not None else int(time.time()))
        return {
            "X-Rescan-Signature": compute_signature(body, secret),
            "X-Rescan-Timestamp": timestamp,
            "Content-Type": "application/json",
        }

    return _make
