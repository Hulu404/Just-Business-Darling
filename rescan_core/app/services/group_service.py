"""Группы 75/25 (B3), детерминированно.

Правило: группа = f(patient_token, pilot_salt). Один и тот же токен всегда
попадает в одну и ту же группу, потому что hash — функция детерминированная.
Контроль получает ровно `control_percent` процентов (по умолчанию 25).

Критерий готовности B3: на 10 000 токенов доля контроля 25 ± 1%, повтор даёт
ту же группу. Тест `test_groups.py` это проверяет.
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
