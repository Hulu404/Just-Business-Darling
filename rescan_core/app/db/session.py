"""Подключение к БД: engine и фабрика сессий (SQLAlchemy 2.x).

Один engine на процесс. Для PostgreSQL включаем пул; для SQLite (тесты) —
статический пул и отключённый check_same_thread, иначе TestClient и потоки
конфликтуют.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()


def _make_engine():
    if settings.is_sqlite:
        return create_engine(
            settings.database_url,
            echo=settings.db_echo,
            connect_args={"check_same_thread": False},
            poolclass=None if ":memory:" in settings.database_url else None,
            future=True,
        )
    return create_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,  # отвалившееся соединение пересоздаётся, а не «падает» запрос
        future=True,
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос, закрывается после ответа."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Контекст для скриптов и задач: commit при успехе, rollback при ошибке."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
