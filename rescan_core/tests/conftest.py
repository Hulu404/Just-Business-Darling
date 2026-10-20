"""Общие фикстуры pytest.

Каждый тест получает отдельную SQLite-базу или временную схему PostgreSQL,
если задан RESCAN_TEST_DATABASE_URL. Сессии конкурентных запросов используют
отдельные соединения; обычный прогон не требует запущенного PostgreSQL.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

# ВАЖНО: импортируем модели ДО обращения к инстансу FastAPI, иначе имя пакета
# `app` и имя инстанса `app` конфликтуют между собой.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models import Clinic, Doctor, Format, Goal
from app.db.session import get_session
from app.main import app as fastapi_app
from app.security.hmac import compute_signature


@pytest.fixture
def empty_engine(tmp_path):
    """Изолированная БД/схема, включая отдельные соединения для тестов гонок."""
    postgres_url = os.environ.get("RESCAN_TEST_DATABASE_URL")
    if postgres_url:
        schema = "test_" + uuid.uuid4().hex
        admin = create_engine(postgres_url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Пулер Supabase не передаёт параметр options, поэтому схему ставим командой
        # на каждом новом соединении и проверяем, что она применилась.
        engine = create_engine(postgres_url)

        @event.listens_for(engine, "connect")
        def use_test_schema(connection, _):
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
                cursor.execute("SHOW search_path")
                assert cursor.fetchone()[0].strip('"') == schema, "search_path не применился"
            connection.commit()
    else:
        engine = create_engine(
            "sqlite+pysqlite:///" + (tmp_path / "test.sqlite3").as_posix(),
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    yield engine
    engine.dispose()
    if postgres_url:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def db_session(empty_engine):
    """Чистая БД на тест + демо-клиника."""
    engine = empty_engine
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
            "X-Rescan-Signature": compute_signature(body, secret, timestamp),
            "X-Rescan-Timestamp": timestamp,
            "Content-Type": "application/json",
        }

    return _make
