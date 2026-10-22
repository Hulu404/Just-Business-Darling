"""B5: Доставка уведомлений (TG + SMS) — успех, тихие часы, ретраи, отписка."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.db.models import (
    AuditEvent,
    Clinic,
    Consent,
    Contact,
    Episode,
    Outbox,
    Patient,
)
from app.security.crypto import encrypt_phone, hash_phone
from app.services.message_service import (
    RETRY_MINUTES,
    deliver_pending_messages,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)  # Дневное время
PHONE = "79001234567"


@pytest.fixture(autouse=True)
def all_logs(caplog):
    caplog.set_level(logging.DEBUG)


@pytest.fixture
def setup_msg(db_session):
    clinic = db_session.execute(select(Clinic)).scalar_one()
    patient = Patient(clinic_id=clinic.id, patient_token="demo-msg-patient", group="main")
    db_session.add(patient)
    db_session.flush()
    db_session.add(Contact(
        patient_id=patient.id,
        phone_enc=encrypt_phone(PHONE),
        phone_hash=hash_phone(PHONE),
        telegram_id=None  # По умолчанию нет ТГ, уйдем в СМС
    ))
    episode = Episode(
        patient_id=patient.id, group="main",
        status="awaiting_doctor", ready_at=datetime.now(UTC),
    )
    db_session.add(episode)
    db_session.commit()
    return patient, episode


@pytest.fixture
def make_task(db_session):
    def _make(episode_id: str, template: str = "default", available_at: datetime = NOW - timedelta(days=1)) -> Outbox:
        row = Outbox(
            topic="notification",
            payload=json.dumps({"episode_id": episode_id, "template": template}),
            status="pending",
            available_at=available_at,
        )
        db_session.add(row)
        db_session.commit()
        return row
    return _make


def deliver(db_session, now=NOW, send=None):
    mock_send = Mock() if send is None else send
    count = deliver_pending_messages(db_session, now, mock_send)
    db_session.commit()
    db_session.expire_all()
    return count, mock_send


# --- успех ---

def test_successful_delivery_sms(db_session, setup_msg, make_task):
    patient, episode = setup_msg
    row = make_task(episode.id, template="doctor_marked")

    count, send = deliver(db_session)

    assert count == 1
    send.assert_called_once()
    # Мок получает 3 аргумента: phone, text, telegram_id
    phone, text, tg_id = send.call_args[0]
    assert phone == PHONE
    assert tg_id is None
    assert "Ваш врач оставил для вас рекомендацию" in text
    assert "http" in text

    db_session.refresh(row)
    assert row.status == "done"
    assert row.attempts == 0


def test_successful_delivery_telegram(db_session, setup_msg, make_task):
    patient, episode = setup_msg
    # Добавляем ТГ ID пациенту
    contact = db_session.execute(select(Contact).where(Contact.patient_id == patient.id)).scalar_one()
    contact.telegram_id = "123456789"
    db_session.commit()
    
    make_task(episode.id)

    _, send = deliver(db_session)

    phone, text, tg_id = send.call_args[0]
    assert tg_id == "123456789"


def test_marketing_consent_affects_text(db_session, setup_msg, make_task):
    patient, episode = setup_msg
    db_session.add(Consent(patient_id=patient.id, kind="marketing", granted=True))
    db_session.commit()
    make_task(episode.id)

    _, send = deliver(db_session)

    assert "записаться к врачу клиники" in send.call_args[0][1]


# --- тихие часы ---

@pytest.mark.parametrize("hour", [21, 22, 23, 0, 8])
def test_quiet_hours_postpone_to_morning(db_session, setup_msg, make_task, hour):
    patient, episode = setup_msg
    row = make_task(episode.id)

    night = NOW.replace(hour=hour)
    count, send = deliver(db_session, now=night)

    assert count == 1
    send.assert_not_called()
    db_session.refresh(row)
    assert row.status == "pending"
    expected = night.replace(hour=9, minute=0, second=0, microsecond=0)
    if hour >= 21:
        expected += timedelta(days=1)
    assert row.available_at.replace(tzinfo=UTC) == expected


# --- ретраи ---

def test_retry_on_failure(db_session, setup_msg, make_task):
    patient, episode = setup_msg
    row = make_task(episode.id)

    def fail(phone, text, tg_id):
        raise TimeoutError("network")

    deliver(db_session, send=fail)

    db_session.refresh(row)
    assert row.status == "pending"
    assert row.attempts == 1
    expected = NOW + timedelta(minutes=RETRY_MINUTES[0])
    assert row.available_at.replace(tzinfo=UTC) == expected


def test_exception_text_is_not_logged(db_session, setup_msg, make_task, caplog):
    patient, episode = setup_msg
    make_task(episode.id)

    def fail(phone, text, tg_id):
        raise TimeoutError(PHONE + " super-secret")

    deliver(db_session, send=fail)

    assert PHONE not in caplog.text
    assert "super-secret" not in caplog.text


# --- отписка и контрольная группа ---

def test_opted_out_patient_is_skipped(db_session, setup_msg, make_task):
    patient, episode = setup_msg
    patient.opted_out = True
    db_session.commit()
    row = make_task(episode.id)

    _, send = deliver(db_session)

    send.assert_not_called()
    db_session.refresh(row)
    assert row.status == "done"
    actions = list(db_session.scalars(select(AuditEvent.action)))
    assert "message.skipped_opted_out" in actions


def test_control_group_is_skipped(db_session, setup_msg, make_task):
    patient, episode = setup_msg
    episode.group = "control"
    db_session.commit()
    row = make_task(episode.id)

    _, send = deliver(db_session)

    send.assert_not_called()
    db_session.refresh(row)
    assert row.status == "done"
    actions = list(db_session.scalars(select(AuditEvent.action)))
    assert "message.skipped_control" in actions


# --- битые задачи ---

def test_missing_episode_marks_failed(db_session):
    row = Outbox(
        topic="notification",
        payload=json.dumps({"episode_id": "missing", "template": "default"}),
        status="pending",
    )
    db_session.add(row)
    db_session.commit()

    _, send = deliver(db_session)

    send.assert_not_called()
    db_session.refresh(row)
    assert row.status == "failed"