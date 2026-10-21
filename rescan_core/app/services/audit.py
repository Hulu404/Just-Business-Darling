"""Аудит (B1): журнал входов и действий.

Пишем в таблицу audit_events. ВАЖНО: в payload — только id и мета, никаких
телефонов и ФИО (требование «логи без ПДн»).
"""
from __future__ import annotations

import json
from datetime import UTC

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import AuditEvent

# Поля, которые запрещено писать в аудит (защита от утечки ПДн в журнал).
_FORBIDDEN_KEYS = {"phone", "fio", "full_name", "patient_name", "email"}


def _sanitize(payload: dict | None) -> str | None:
    if not payload:
        return None
    clean = {k: v for k, v in payload.items() if k.lower() not in _FORBIDDEN_KEYS}
    return json.dumps(clean, ensure_ascii=False, default=str)


def record(
    session: Session,
    *,
    action: str,
    actor_id: str | None = None,
    role: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    payload: dict | None = None,
    commit: bool = False,
) -> AuditEvent:
    """Записать событие аудита. commit=False по умолчанию — чтобы попадать в
    ту же транзакцию, что и бизнес-действие."""
    event = AuditEvent(
        created_at=utcnow().astimezone(UTC),
        actor_id=actor_id,
        role=role,
        action=action,
        entity=entity,
        entity_id=entity_id,
        payload=_sanitize(payload),
    )
    session.add(event)
    if commit:
        session.commit()
    return event
