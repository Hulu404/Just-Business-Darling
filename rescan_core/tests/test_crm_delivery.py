"""B7: заявки создаются непосредственно в БД; внешней сети нет."""
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db.models import (
    AuditEvent,
    Clinic,
    Contact,
    Doctor,
    Format,
    Goal,
    Outbox,
    Patient,
    Request,
)
from app.security.crypto import encrypt_phone, hash_phone
from app.security.hmac import compute_signature
from tests.fake_crm import fake_crm

NOW = datetime(2026, 10, 20, 10, tzinfo=UTC)
PHONE = "70000000000"
SECRET = "dev-fake-webhook-secret"


@pytest.fixture(autouse=True)
def all_logs(caplog):
    # Проверка «телефона нет в логах» видит и отладочные записи, не только ошибки.
    caplog.set_level(logging.DEBUG)


@pytest.fixture
def application(db_session, monkeypatch):
    clinic = db_session.scalar(select(Clinic))
    patient = Patient(clinic_id=clinic.id, patient_token="demo-crm-patient", group="main")
    db_session.add(patient)
    db_session.flush()
    db_session.add(Contact(patient_id=patient.id, phone_enc=encrypt_phone(PHONE),
                           phone_hash=hash_phone(PHONE)))
    request = Request(
        patient_id=patient.id, doctor_id=db_session.scalar(select(Doctor.id)),
        format_id=db_session.scalar(select(Format.id)), goal_id=db_session.scalar(select(Goal.id)),
        window="morning", created_at=NOW,
    )
    db_session.add(request)
    db_session.flush()
    row = Outbox(topic="crm", payload=json.dumps({"request_id": request.id}))
    db_session.add(row)
    db_session.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "crm_targets", {})
    monkeypatch.setattr(settings, "notify_targets", {})
    monkeypatch.setattr(settings, "mis_clinic_id", clinic.id)
    return clinic, patient, request, row


def deliver(session, now=NOW, send=None):
    from app.services.crm_service import deliver_pending
    # Без send работает отправка по умолчанию — http_send.
    result = deliver_pending(session, now) if send is None else deliver_pending(session, now, send)
    session.commit()
    session.expire_all()
    return result


def target(clinic, url, kind="webhook"):
    get_settings().crm_targets[clinic.id] = {"kind": kind, "url": url, "secret": SECRET}


def notification(clinic, url):
    get_settings().notify_targets[clinic.id] = {"url": url, "secret": SECRET}


def notify_audit(session):
    rows = session.scalars(select(AuditEvent).where(AuditEvent.action == "crm.notify_sent"))
    return [json.loads(row.payload) for row in rows]


def assert_private(session, caplog, *values):
    rows = session.scalars(select(Outbox)).all()
    audits = session.scalars(select(AuditEvent)).all()
    text = repr([(r.topic, r.payload) for r in rows])
    text += repr([(a.action, a.payload, a.actor_id, a.entity_id) for a in audits])
    text += caplog.text
    for value in (PHONE, SECRET, *values):
        assert value not in text


@pytest.mark.parametrize("kind", ["bitrix24", "webhook"])
def test_delivery_http_fields_signature_and_privacy(db_session, application, caplog, kind):
    clinic, patient, request, row = application
    with fake_crm(response={"result": 123, "crm_request_id": "demo-lead"}) as (url, received):
        target(clinic, url, kind)
        assert deliver(db_session) == 1
        assert deliver(db_session) == 0
        assert len(received) == 1
        path, headers, raw = received[0]
        body = json.loads(raw)
        if kind == "bitrix24":
            assert path == "/crm.lead.add.json"
            assert body["fields"] == {
                "TITLE": "Заявка rescan: Цель",
                "PHONE": [{"VALUE": PHONE, "VALUE_TYPE": "MOBILE"}],
                "COMMENTS": "Врач: Тестовый Врач\nФормат: Приём\nОкно: morning",
                "SOURCE_DESCRIPTION": "rescan",
            }
            assert request.crm_request_id == "123"
        else:
            assert body == {
                "request_id": request.id, "clinic_id": clinic.id,
                "patient_token": patient.patient_token, "phone": PHONE,
                "doctor": {"external_id": "doc-1", "name": "Тестовый Врач"},
                "format": {"title": "Приём", "price_kopecks": 100000},
                "window": {"code": "morning", "title": None},
                "goal": {"title": "Цель"}, "created_at": NOW.isoformat(),
            }
            assert headers["X-Rescan-Signature"] == compute_signature(
                raw, SECRET, headers["X-Rescan-Timestamp"])
            assert request.crm_request_id == "demo-lead"
        assert request.status == "sent"
        assert row.status == "done" and row.processed_at is not None
        assert row.attempts == 0
        assert db_session.scalar(select(AuditEvent.action)) == "crm.request_sent"
        assert_private(db_session, caplog, url)


@pytest.mark.parametrize("response", [{}, {"error": "demo-failure"}, {"result": None}])
def test_bitrix_requires_result(db_session, application, response):
    clinic, _, request, row = application
    with fake_crm(response=response) as (url, _):
        target(clinic, url, "bitrix24")
        deliver(db_session)
    assert request.status == "new"
    assert row.status == "pending" and row.attempts == 1


def test_retries_then_notify(db_session, application, caplog):
    clinic, _, request, row = application
    with fake_crm(status=503) as (url, received), fake_crm(response={}) as (backup, notifications):
        target(clinic, url)
        notification(clinic, backup)
        now = NOW
        for attempt, minutes in enumerate([1, 5, 15, 60], 1):
            deliver(db_session, now)
            assert row.attempts == attempt and row.status == "pending"
            scheduled = row.available_at.replace(tzinfo=UTC)
            assert scheduled == now + timedelta(minutes=minutes)
            assert deliver(db_session, scheduled - timedelta(seconds=1)) == 0
            now = scheduled
        deliver(db_session, now)
        assert row.attempts == 5 and row.status == "failed"
        deliver(db_session, now)
        assert len(received) == 5 and len(notifications) == 1
        path, headers, raw = notifications[0]
        body = json.loads(raw)
        assert set(body) == {
            "request_id", "clinic_id", "phone", "doctor", "format", "window", "goal", "reason",
        }
        assert body["reason"] == "crm_failed" and body["phone"] == PHONE
        assert headers["X-Rescan-Signature"] == compute_signature(
            raw, SECRET, headers["X-Rescan-Timestamp"])
        # Уведомление администратору — не отправка в CRM: заявка остаётся new.
        assert request.status == "new"
        actions = list(db_session.scalars(select(AuditEvent.action)))
        assert "crm.request_failed" in actions and "crm.request_sent" not in actions
        assert notify_audit(db_session) == [{"reason": "crm_failed"}]
        assert db_session.scalar(select(Outbox).where(Outbox.topic == "notify")).status == "done"
        assert_private(db_session, caplog, url, backup)


def test_no_crm_goes_to_notify(db_session, application):
    clinic, _, request, row = application
    with fake_crm(response={}) as (url, received):
        notification(clinic, url)
        deliver(db_session)
        deliver(db_session)
        assert len(received) == 1
        assert json.loads(received[0][2])["reason"] == "no_crm"
        assert request.status == "new"
        assert notify_audit(db_session) == [{"reason": "no_crm"}]
        actions = list(db_session.scalars(select(AuditEvent.action)))
        assert "crm.request_sent" not in actions
        assert row.status == "done"
        backup = db_session.scalar(select(Outbox).where(Outbox.topic == "notify"))
        assert json.loads(backup.payload) == {"request_id": request.id}


def test_no_channels_fails_without_private_logs(db_session, application, caplog):
    deliver(db_session)
    deliver(db_session)
    backup = db_session.scalar(select(Outbox).where(Outbox.topic == "notify"))
    assert backup.status == "failed"
    assert "crm.no_channel" in list(db_session.scalars(select(AuditEvent.action)))
    assert "crm.no_channel" in caplog.text
    assert_private(db_session, caplog)


@pytest.mark.parametrize("topic", ["crm", "notify"])
def test_opted_out_never_sent(db_session, application, topic):
    clinic, patient, request, row = application
    row.topic = topic
    patient.opted_out = True
    db_session.commit()
    with fake_crm() as (url, received):
        target(clinic, url)
        notification(clinic, url)
        deliver(db_session)
        assert received == []
    assert request.status == "cancelled"
    assert row.status == "done"
    assert db_session.scalar(select(AuditEvent.action)) == "crm.skipped_opted_out"


@pytest.mark.parametrize("error", [TimeoutError, OSError])
def test_transport_exception_is_private(db_session, application, caplog, error):
    clinic, _, _, row = application
    target(clinic, "http://127.0.0.1/demo-secret")

    def fail(*args):
        raise error(PHONE + SECRET)

    deliver(db_session, send=fail)
    assert row.attempts == 1
    assert_private(db_session, caplog, "http://127.0.0.1/demo-secret")


def test_redirect_never_forwards_phone(db_session, application):
    clinic, _, _, row = application
    with fake_crm() as (destination, stolen):
        with fake_crm(status=307, headers={"Location": destination}) as (url, _):
            target(clinic, url)
            deliver(db_session)
    assert stolen == []
    assert row.attempts == 1


def production():
    return {
        "environment": "production", "mis_hmac_secret": "h" * 32, "pilot_salt": "p" * 32,
        "contact_encryption_key": "e" * 32, "contact_hash_salt": "s" * 32,
        "crm_status_secret": "c" * 32, "patient_link_secret": "l" * 32,
        "staff_tokens": {}, "mis_clinic_id": "demo-clinic",
    }


@pytest.mark.parametrize("field", ["crm_targets", "notify_targets"])
@pytest.mark.parametrize("url", ["http://example.invalid/demo", "file:///demo",
                                "https://?demo-private", "http://127.0.0.1.evil.invalid"])
def test_invalid_targets_private(field, url):
    values = production()
    values[field] = {"demo": {"url": url, "secret": "x" * 32}}
    if field == "crm_targets":
        values[field]["demo"]["kind"] = "webhook"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **values)
    assert url not in str(error.value)


@pytest.mark.parametrize("field", ["crm_targets", "notify_targets"])
@pytest.mark.parametrize("secret", ["", "short", "dev-" + "s" * 32])
def test_production_target_secrets(field, secret):
    values = production()
    values[field] = {"demo": {"url": "https://example.invalid/demo", "secret": secret}}
    if field == "crm_targets":
        values[field]["demo"]["kind"] = "webhook"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_settings_from_environment(monkeypatch):
    targets = {"demo": {"kind": "webhook", "url": "http://127.0.0.1:1234", "secret": SECRET}}
    monkeypatch.setenv("CRM_TARGETS", json.dumps(targets))
    monkeypatch.setenv("NOTIFY_TARGETS", json.dumps(targets))
    # CRM-specific kind is forbidden for the notification channel.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="test")
    monkeypatch.setenv("NOTIFY_TARGETS", "{}")
    monkeypatch.setenv("CRM_STATUS_SECRET", SECRET)
    settings = Settings(_env_file=None, environment="test")
    assert settings.crm_targets == targets and settings.crm_status_secret == SECRET
    assert SECRET not in repr(settings)


@pytest.mark.parametrize("value", ["", "dev-demo", "short"])
def test_production_status_secret_required(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(production() | {"crm_status_secret": value}))


def test_missing_production_status_secret(monkeypatch):
    monkeypatch.delenv("CRM_STATUS_SECRET", raising=False)
    values = production()
    del values["crm_status_secret"]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_reads_contact_and_names_at_delivery(db_session, application, caplog):
    clinic, patient, request, _ = application
    contact = db_session.scalar(select(Contact).where(Contact.patient_id == patient.id))
    contact.phone_enc = encrypt_phone("70000000001")
    doctor = db_session.get(Doctor, request.doctor_id)
    doctor.full_name = "Демо Новый Врач"
    db_session.commit()
    with fake_crm(response={}) as (url, received):
        target(clinic, url)
        deliver(db_session)
        payload = json.loads(received[0][2])
        assert payload["phone"] == "70000000001"
        assert payload["doctor"]["name"] == "Демо Новый Врач"
        assert request.crm_request_id is None
        assert request.status == "sent"
        assert_private(db_session, caplog, url, "70000000001")


def test_window_title_from_b6_settings(db_session, application):
    clinic, _, _, _ = application
    # До слияния B6 — атрибут только в памяти ORM, без изменения его модели.
    clinic.patient_settings = json.dumps(
        {"windows": [{"code": "morning", "title": "Демо утро"}]})
    with fake_crm(response={}) as (url, received):
        target(clinic, url)
        deliver(db_session)
        assert json.loads(received[0][2])["window"] == {"code": "morning", "title": "Демо утро"}


@pytest.mark.parametrize("raw", ["", "not-json", "[]", '{"windows": {}}',
                                 '{"windows": [{"code": "morning", "title": 1}]}'])
def test_window_title_null_without_valid_settings(db_session, application, raw):
    clinic, _, request, row = application
    clinic.patient_settings = raw
    with fake_crm(response={}) as (url, received):
        target(clinic, url)
        deliver(db_session)
        assert json.loads(received[0][2])["window"] == {"code": "morning", "title": None}
    assert row.status == "done" and request.status == "sent"


def test_default_sender_is_http_send():
    import inspect

    from app.services.crm_service import deliver_pending
    from app.services.crm_transports import http_send
    assert inspect.signature(deliver_pending).parameters["send"].default is http_send


def test_notify_exhaustion_is_finite(db_session, application, caplog):
    clinic, _, _, _ = application
    with fake_crm(status=500) as (url, received):
        notification(clinic, url)
        now = NOW
        for minutes in (1, 5, 15, 60, 0):
            deliver(db_session, now)
            now += timedelta(minutes=minutes)
        assert deliver(db_session, now) == 0
        assert len(received) == 5
        backup = db_session.scalar(select(Outbox).where(Outbox.topic == "notify"))
        assert backup.status == "failed" and backup.attempts == 5
        assert len(db_session.scalars(select(Outbox)).all()) == 2
        assert_private(db_session, caplog, url)


@pytest.mark.parametrize("status", ["booked", "cancelled"])
def test_terminal_request_not_sent(db_session, application, status):
    clinic, _, request, row = application
    request.status = status
    db_session.commit()
    with fake_crm() as (url, received):
        target(clinic, url)
        deliver(db_session)
        assert received == []
    assert row.status == "done" and request.status == status


def test_other_topics_and_future_rows_untouched(db_session, application):
    _, _, _, row = application
    row.available_at = NOW + timedelta(seconds=1)
    other = Outbox(topic="sms", payload='{"demo": true}')
    db_session.add(other)
    db_session.commit()
    assert deliver(db_session) == 0
    assert row.status == other.status == "pending"


def test_http_timeout_is_ten_seconds(monkeypatch):
    from app.services import crm_transports

    observed = []

    class Opener:
        def open(self, request, timeout):
            observed.append(timeout)
            raise TimeoutError("demo-private-url")

    monkeypatch.setattr(crm_transports, "build_opener", lambda *args: Opener())
    with pytest.raises(crm_transports.DeliveryError) as error:
        crm_transports.http_send("notify", {"url": "http://127.0.0.1", "secret": SECRET}, {})
    assert observed == [10]
    assert "demo-private-url" not in str(error.value)


@pytest.mark.parametrize("kind", ["bitrix24", "webhook"])
def test_valid_production_targets(kind):
    values = production()
    values["crm_targets"] = {
        "demo": {"kind": kind, "url": "https://example.invalid/demo", "secret": "x" * 32},
    }
    values["notify_targets"] = {
        "demo": {"url": "https://example.invalid/notify", "secret": "y" * 32},
    }
    assert Settings(_env_file=None, **values).crm_targets == values["crm_targets"]


@pytest.mark.parametrize("url", ["http://example.invalid/demo", "ftp://127.0.0.1/demo",
                                "https://user:password@example.invalid/demo"])
def test_local_also_rejects_unsafe_targets(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="local", crm_targets={
            "demo": {"kind": "webhook", "url": url, "secret": SECRET},
        })


@pytest.mark.parametrize("kind", ["webhook", "notify"])
def test_signed_channel_requires_secret_even_locally(kind):
    name = "crm_targets" if kind == "webhook" else "notify_targets"
    target_value = {"url": "http://127.0.0.1/demo"}
    if kind == "webhook":
        target_value["kind"] = kind
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="test", **{name: {"demo": target_value}})


needs_postgres = pytest.mark.skipif(
    not os.environ.get("RESCAN_TEST_DATABASE_URL"), reason="гонки проверяются на PostgreSQL",
)


@needs_postgres
def test_two_workers_send_once(db_session, application):
    clinic, _, _, _ = application
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    barrier = threading.Barrier(2)
    with fake_crm() as (url, received):
        target(clinic, url)

        def worker():
            with factory() as session:
                barrier.wait(timeout=10)
                return deliver(session)

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        assert sum(results) == 1 and len(received) == 1
