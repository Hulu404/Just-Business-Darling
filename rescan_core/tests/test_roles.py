"""Тесты ролей (B1)."""
from __future__ import annotations

from app.security.roles import Role, resolve_role


def test_known_token_resolves_to_role():
    role, actor = resolve_role("dev-admin-token")
    assert role == Role.ADMINISTRATOR
    assert actor == "dev-admin"


def test_unknown_token_is_none():
    assert resolve_role("nope") is None
    assert resolve_role(None) is None
