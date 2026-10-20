"""Истечение срока отметки врача (B4).

Запуск:  python -m scripts.expire_queue

Эпизоды без отметки со сроком в прошлом переходят в `default_message`.
Повторный запуск ничего не меняет. Планировщик подключается в B5.
"""
from __future__ import annotations

from app.db.base import utcnow
from app.db.session import session_scope
from app.services.queue_service import expire_overdue


def main() -> int:
    with session_scope() as session:
        expired = expire_overdue(session, utcnow())
    print(f"Срок отметки истёк у эпизодов: {expired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
