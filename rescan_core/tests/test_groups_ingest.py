"""B3: группа в подписанном HTTP-ответе и БД переживает новые события и настройки."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Episode, Patient
from app.services.group_service import assign_group

SALT_A = "demo-b3-salt-a"
SALT_B = "demo-b3-salt-b"
# На соли A: 3469 (main) и 2416 (control); на соли B: 1370 и 2525.
PATIENTS = [("demo-b3-patient-19", "main"), ("demo-b3-patient-6", "control")]


@pytest.fixture
def group_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "pilot_salt", SALT_A)
    monkeypatch.setattr(settings, "control_percent", 25)
    return settings


def post_event(client, sign_headers, patient_token, event_id):
    body = json.dumps({
        "event_id": event_id,
        "branch_id": "demo-b3-branch",
        "patient_token": patient_token,
        "phone": "+70000000000",
        "ordering_doctor_id": "doc-1",
        "ready_at": "2026-10-19T09:00:00Z",
        "marketing_consent": False,
    }).encode()
    response = client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    assert response.status_code == 202
    result = response.json()
    assert result["status"] == "created"
    return result


@pytest.mark.parametrize(("patient_token", "expected_group"), PATIENTS)
@pytest.mark.parametrize("change", ["none", "salt", "percent"])
def test_saved_group_survives_new_event_and_settings_change(
    client, sign_headers, db_session, group_settings, monkeypatch,
    patient_token, expected_group, change,
):
    first = post_event(client, sign_headers, patient_token, "demo-b3-first")
    assert first["group"] == expected_group

    if change == "salt":
        monkeypatch.setattr(group_settings, "pilot_salt", SALT_B)
    elif change == "percent":
        percent = 0 if expected_group == "control" else 50
        monkeypatch.setattr(group_settings, "control_percent", percent)
    if change != "none":
        # Новый расчёт дал бы другую группу: тест заметит ошибочный пересчёт.
        assert assign_group(patient_token).value != expected_group

    # Читаем сохранённые строки заново, не полагаясь на identity map сессии.
    db_session.expire_all()
    second = post_event(client, sign_headers, patient_token, "demo-b3-second")
    assert second["group"] == expected_group
    assert second["episode_id"] != first["episode_id"]

    db_session.expire_all()
    patient = db_session.execute(select(Patient)).scalar_one()
    assert patient.patient_token == patient_token
    assert patient.group == expected_group
    episodes = db_session.execute(select(Episode)).scalars().all()
    assert {episode.id for episode in episodes} == {first["episode_id"], second["episode_id"]}
    assert all(episode.patient_id == patient.id for episode in episodes)
    assert all(episode.group == expected_group for episode in episodes)
