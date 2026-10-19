"""Тесты групп 75/25 (B3).

Критерий готовности: на 10 000 токенов доля контроля 25 ± 1%,
повторное событие даёт ту же группу.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.group_service import Group, assign_group


def test_same_token_same_group():
    a = assign_group("patient-42")
    b = assign_group("patient-42")
    assert a == b  # детерминированность


@pytest.mark.parametrize("salt", ["demo-b3-salt-a", "demo-b3-salt-b"])
def test_control_share_is_about_25_percent(salt):
    groups = [assign_group(f"pt-{i}", salt=salt, control_percent=25) for i in range(10_000)]
    control_share = groups.count(Group.CONTROL) / len(groups)
    assert 0.24 <= control_share <= 0.26, f"доля контроля {control_share:.3f}"


def test_group_values_are_main_or_control():
    assert assign_group("x") in (Group.MAIN, Group.CONTROL)


@pytest.mark.parametrize("environment", ["local", "test", "staging", "production"])
@pytest.mark.parametrize("percent", [-1, 51, 100])
def test_invalid_control_percent_is_rejected_without_printing_values(environment, percent):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, environment=environment, control_percent=percent,
                 pilot_salt="demo-must-not-appear-in-errors")
    message = str(error.value)
    assert "control_percent" in message
    assert "greater than or equal to 0" in message or "less than or equal to 50" in message
    assert "input_value" not in message
    assert "demo-must-not-appear-in-errors" not in message


@pytest.mark.parametrize("percent", [0, 25, 50])
def test_control_percent_boundaries_are_allowed(percent):
    settings = Settings(_env_file=None, environment="test", control_percent=percent)
    assert settings.control_percent == percent


@pytest.mark.parametrize("environment", ["production", "staging", "Production"])
@pytest.mark.parametrize("salt", ["", "   "])
def test_empty_pilot_salt_is_rejected_outside_local_and_test(environment, salt):
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            environment=environment,
            mis_hmac_secret="demo-hmac-" + "a" * 32,
            pilot_salt=salt,
            contact_encryption_key="demo-encryption-" + "b" * 32,
            contact_hash_salt="demo-hash-" + "c" * 32,
            staff_tokens={},
            mis_clinic_id="demo-clinic",
        )
    message = str(error.value)
    assert "pilot_salt" in message
    assert "32" in message
    assert "input_value" not in message
    assert "demo-hmac-" not in message
    assert "demo-encryption-" not in message
    assert "demo-hash-" not in message


@pytest.mark.parametrize("environment", ["local", "test"])
def test_empty_pilot_salt_is_allowed_for_local_and_test(environment):
    assert Settings(_env_file=None, environment=environment, pilot_salt="").pilot_salt == ""
