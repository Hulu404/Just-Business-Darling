"""Роли и служебные токены (B1: роли врач / администратор / руководитель).

В проде роль выдаёт шлюз (он раздаёт интерфейсы). Здесь — простой слой,
чтобы ручки можно было защитить и протестировать уже сейчас. Токен → роль
берём из настроек (`staff_tokens`), в проде этот словарь заменяется вызовом шлюза.
"""
from __future__ import annotations

from enum import StrEnum

from fastapi import Header, HTTPException, status

from app.config import get_settings


class Role(StrEnum):
    DOCTOR = "doctor"
    ADMINISTRATOR = "administrator"
    MANAGER = "manager"  # руководитель


def resolve_role(token: str | None) -> tuple[Role, str] | None:
    """Вернуть (роль, actor_id) по токену или None, если токен неизвестен."""
    if not token:
        return None
    settings = get_settings()
    entry = settings.staff_tokens.get(token)
    if entry is None:
        return None
    try:
        return Role(entry.role), entry.actor_id
    except ValueError:
        return None


async def require_staff(
    x_staff_token: str | None = Header(default=None, alias="X-Staff-Token"),
) -> tuple[Role, str]:
    """Любой сотрудник (врач / администратор / руководитель)."""
    resolved = resolve_role(x_staff_token)
    if resolved is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown staff token")
    return resolved


def require_roles(*allowed: Role):
    """Фабрика зависимости: пускает только перечисленные роли."""

    async def _dep(
        x_staff_token: str | None = Header(default=None, alias="X-Staff-Token"),
    ) -> tuple[Role, str]:
        resolved = resolve_role(x_staff_token)
        if resolved is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown staff token")
        role, actor_id = resolved
        if role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role not allowed")
        return role, actor_id

    return _dep
