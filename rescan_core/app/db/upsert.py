"""Атомарная вставка по конкретному уникальному ключу (PostgreSQL и SQLite)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import Insert as SqliteInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.base import Base


def insert_unique[ModelT: Base](
    session: Session, model: type[ModelT], key: dict[str, Any], **values: Any,
) -> tuple[ModelT, bool]:
    """Ждём конкурирующую транзакцию; другие ошибки БД не маскируем дублем."""
    dialect = session.get_bind().dialect.name
    statement: PgInsert | SqliteInsert
    if dialect == "postgresql":
        statement = pg_insert(model).values(**key, **values).on_conflict_do_nothing(
            index_elements=list(key),
        )
    elif dialect == "sqlite":
        statement = sqlite_insert(model).values(**key, **values).on_conflict_do_nothing(
            index_elements=list(key),
        )
    else:
        raise ValueError("Поддерживаются PostgreSQL и SQLite")
    inserted = session.execute(statement.returning(model.__table__.c.id)).scalar_one_or_none()
    row = session.execute(select(model).filter_by(**key)).scalar_one()
    return row, inserted is not None
