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
from sqlalchemy.schema import CreateIndex, CreateTable

# ВАЖНО: импортируем модели ДО обращения к инстансу FastAPI, иначе имя пакета
# `app` и имя инстанса `app` конфликтуют между собой.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models import Clinic, Doctor, Format, Goal
from app.db.session import get_session
from app.main import app as fastapi_app
from app.security.hmac import compute_signature

POSTGRES_URL = os.environ.get("RESCAN_TEST_DATABASE_URL")
_current_schema: list[str] = []


@pytest.fixture(scope="session")
def postgres_engine():
    """Один пул соединений на весь прогон: соединение с удалённым пулером стоит секунды.

    Пулер Supabase не передаёт параметр options, поэтому схему теста ставим командой
    при каждой выдаче соединения из пула и проверяем, что она применилась.
    """
    engine = create_engine(POSTGRES_URL)

    @event.listens_for(engine, "checkout")
    def use_test_schema(connection, _record, _proxy):
        schema = _current_schema[-1] if _current_schema else "pg_catalog"
        # Одним запросом вне транзакции: без BEGIN и COMMIT это один обмен с базой.
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('search_path', %s, false)", (f'"{schema}"',))
                assert cursor.fetchone()[0].strip('"') == schema, "search_path не применился"
        finally:
            connection.autocommit = False

    yield engine
    engine.dispose()


def create_tables(engine) -> None:
    """Таблицы моделей. На PostgreSQL — одним запросом: каждый запрос к удалённой базе стоит
    полсекунды, а create_all делает их десятки."""
    if engine.dialect.name != "postgresql":
        Base.metadata.create_all(engine)
        return
    statements = []
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=engine.dialect)))
        statements += [str(CreateIndex(index).compile(dialect=engine.dialect))
                       for index in table.indexes]
    with engine.begin() as conn:
        conn.exec_driver_sql(";\n".join(statements))


@pytest.fixture
def empty_engine(tmp_path, request):
    """Изолированная БД/схема, включая отдельные соединения для тестов гонок."""
    if POSTGRES_URL:
        engine = request.getfixturevalue("postgres_engine")
        schema = "test_" + uuid.uuid4().hex
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        _current_schema.append(schema)
        yield engine
        _current_schema.pop()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        return
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


@pytest.fixture
def db_session(empty_engine):
    """Чистая БД на тест + демо-клиника."""
    engine = empty_engine
    create_tables(engine)
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
