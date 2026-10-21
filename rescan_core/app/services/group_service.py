"""Группы 75/25 (B3), детерминированно.

Правило: группа = f(patient_token, pilot_salt). При одинаковых настройках
расчёт детерминированный. Доля контроля стремится к `control_percent`
(по умолчанию 25), но не обязана точно совпадать на конечной выборке.

Назначение сохраняется в patients.group при первом событии. Для следующих
эпизодов ingest использует сохранённую группу, даже после смены настроек.
Тесты test_groups.py и test_groups_ingest.py закрепляют оба свойства.
"""
from __future__ import annotations

import hashlib
from enum import StrEnum

from app.config import get_settings


class Group(StrEnum):
    MAIN = "main"
    CONTROL = "control"


def _bucket(patient_token: str, salt: str) -> int:
    """Детерминированное число 0..9999 из токена и соли."""
    digest = hashlib.sha256(f"{salt}:{patient_token}".encode()).hexdigest()
    return int(digest[:8], 16) % 10_000


def assign_group(patient_token: str, *, salt: str | None = None,
                 control_percent: int | None = None) -> Group:
    """Определить группу. Границы: контроль — если bucket < порог."""
    settings = get_settings()
    salt = salt if salt is not None else settings.pilot_salt
    percent = control_percent if control_percent is not None else settings.control_percent

    threshold = int(percent * 100)  # 25% -> 2500 из 10000
    if _bucket(patient_token, salt) < threshold:
        return Group.CONTROL
    return Group.MAIN
