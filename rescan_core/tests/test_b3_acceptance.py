"""Приёмочные тесты B3 (группы) по разделу «Контракты» задания 18.

Чёрный ящик: события идут через HTTP с подписью, как в test_ingest.py; результат
смотрим в ответе и в таблицах, названных в контракте (patients.group, episodes.group,
episodes.status). Внутренности group_service не используются, кроме assign_group —
публичного правила, по которому подбираются токены нужной группы.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.models import Episode, Patient
from app.services.group_service import Group, assign_group

EVENT = {
    "branch_id": "br-1",
    "phone": "+7 (900) 000-00-01",
    "ordering_doctor_id": "doc-1",
    "ready_at": "2026-10-14T09:00:00+03:00",
    "marketing_consent": True,
}
TOKENS = 10_000


def send(client, sign_headers, event_id: str, token: str):
    body = json.dumps({**EVENT, "event_id": event_id, "patient_token": token}).encode()
    response = client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    assert response.status_code == 202, response.text
    return response.json()


def token_in(group: Group, prefix: str = "b3-pt-") -> str:
    """Первый синтетический токен, который по текущим настройкам попадает в группу."""
    return next(f"{prefix}{i}" for i in range(1000) if assign_group(f"{prefix}{i}") == group)


def episodes_of(db_session, token: str) -> list[Episode]:
    db_session.expire_all()
    patient = db_session.execute(
        select(Patient).where(Patient.patient_token == token)).scalar_one()
    return list(db_session.execute(
        select(Episode).where(Episode.patient_id == patient.id)).scalars())


@pytest.mark.parametrize("group", [Group.MAIN, Group.CONTROL])
def test_repeat_event_keeps_group_in_response_and_new_episode(client, sign_headers,
                                                              db_session, group):
    token = token_in(group)
    first = send(client, sign_headers, "b3-repeat-1", token)
    second = send(client, sign_headers, "b3-repeat-2", token)
    assert first["status"] == second["status"] == "created"
    assert first["group"] == second["group"] == group.value
    episodes = episodes_of(db_session, token)
    assert len(episodes) == 2
    assert {e.group for e in episodes} == {group.value}


@pytest.mark.parametrize("setting", ["pilot_salt", "control_percent"])
def test_changed_settings_do_not_regroup_recorded_patient(client, sign_headers, db_session,
                                                          monkeypatch, setting):
    settings = get_settings()
    monkeypatch.setattr(settings, "control_percent", 25)
    if setting == "pilot_salt":
        token = token_in(Group.MAIN)
        # соль, при которой этот токен по правилу ушёл бы в контроль
        changed = next(f"b3-other-salt-{i}" for i in range(1000)
                       if assign_group(token, salt=f"b3-other-salt-{i}") == Group.CONTROL)
    else:
        # токен, который при 25% в основной группе, а при 50% был бы в контроле
        token = next(f"b3-move-{i}" for i in range(5000)
                     if assign_group(f"b3-move-{i}") == Group.MAIN
                     and assign_group(f"b3-move-{i}", control_percent=50) == Group.CONTROL)
        changed = 50
    first = send(client, sign_headers, "b3-settings-1", token)
    assert first["group"] == "main"
    monkeypatch.setattr(settings, setting, changed)
    assert assign_group(token) == Group.CONTROL  # правило с новыми настройками дало бы контроль
    second = send(client, sign_headers, "b3-settings-2", token)
    assert second["group"] == "main"
    assert {e.group for e in episodes_of(db_session, token)} == {"main"}


@pytest.mark.parametrize("salt", ["b3-salt-one", "b3-salt-two"])
def test_control_share_is_25_percent_on_two_salts(salt):
    groups = [assign_group(f"syn-{i}", salt=salt, control_percent=25) for i in range(TOKENS)]
    share = groups.count(Group.CONTROL) / TOKENS
    assert 0.24 <= share <= 0.26, f"соль {salt}: доля контроля {share:.4f}"


@pytest.mark.parametrize("percent", [-1, 51, 100])
def test_control_percent_outside_0_50_is_config_error(percent):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, control_percent=percent)
    assert "control_percent" in str(error.value)
    assert f"input_value={percent}" not in str(error.value)


@pytest.mark.parametrize("percent", [0, 25, 50])
def test_control_percent_bounds_are_allowed(percent):
    assert Settings(_env_file=None, control_percent=percent).control_percent == percent


def production(**overrides):
    values = {
        "environment": "production",
        "mis_hmac_secret": "qa-hmac-" + "a" * 32,
        "pilot_salt": "qa-pilot-" + "b" * 32,
        "contact_encryption_key": "qa-key-" + "c" * 32,
        "contact_hash_salt": "qa-hash-" + "d" * 32,
        "patient_link_secret": "qa-link-" + "e" * 32,
        "crm_status_secret": "qa-crm-" + "e" * 32,
        "staff_tokens": {},
        "mis_clinic_id": "qa-clinic",
    }
    return {**values, **overrides}


@pytest.mark.parametrize("salt", ["", "   "])
def test_empty_pilot_salt_outside_local_is_config_error_without_values(salt):
    values = production(pilot_salt=salt)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **values)
    text = str(error.value)
    assert "pilot_salt" in text
    for secret in ("mis_hmac_secret", "contact_encryption_key", "contact_hash_salt"):
        assert values[secret] not in text


@pytest.mark.parametrize("environment", ["local", "test"])
def test_local_and_test_start_with_default_salt(environment):
    assert Settings(_env_file=None, environment=environment).pilot_salt


def test_production_with_valid_group_settings_starts():
    assert Settings(_env_file=None, **production(control_percent=25)).control_percent == 25


@pytest.mark.parametrize("group, status", [(Group.CONTROL, "control"),
                                           (Group.MAIN, "awaiting_doctor")])
def test_episode_status_follows_group(client, sign_headers, db_session, group, status):
    token = token_in(group)
    result = send(client, sign_headers, f"b3-status-{group.value}", token)
    assert result["group"] == group.value
    (episode,) = episodes_of(db_session, token)
    assert episode.status == status
