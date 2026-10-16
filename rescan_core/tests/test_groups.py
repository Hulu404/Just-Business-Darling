"""Тесты групп 75/25 (B3).

Критерий готовности: на 10 000 токенов доля контроля 25 ± 1%,
повторное событие даёт ту же группу.
"""
from __future__ import annotations

from app.services.group_service import Group, assign_group


def test_same_token_same_group():
    a = assign_group("patient-42")
    b = assign_group("patient-42")
    assert a == b  # детерминированность


def test_control_share_is_about_25_percent():
    groups = [assign_group(f"pt-{i}") for i in range(10_000)]
    control_share = groups.count(Group.CONTROL) / len(groups)
    assert 0.24 <= control_share <= 0.26, f"доля контроля {control_share:.3f}"


def test_group_values_are_main_or_control():
    assert assign_group("x") in (Group.MAIN, Group.CONTROL)
