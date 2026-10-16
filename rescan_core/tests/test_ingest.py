"""Тесты приёма событий (B2) и записи в БД (B1): идемпотентность, контракт, аудит."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.db.models import AuditEvent, Contact, Episode, Event, Patient
from app.security.crypto import decrypt_phone

EVENT = {
    "event_id": "evt-001",
    "branch_id": "br-1",
    "patient_token": "pt-abc",
    "phone": "+7 (900) 123-45-67",
    "ordering_doctor_id": "doc-1",
    "ready_at": "2026-10-14T09:00:00+03:00",
    "marketing_consent": True,
}


def test_event_created_once(client, sign_headers):
    body = json.dumps(EVENT).encode()
    r = client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "created"
    assert data["episode_id"]  # эпизод реально создан
    assert data["group"] in ("main", "control")


def test_duplicate_event_is_idempotent(client, sign_headers, db_session):
    body = json.dumps(EVENT).encode()
    client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    second = client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    assert second.json()["status"] == "duplicate"
    # В базе ровно один эпизод — второй не создан.
    assert len(db_session.execute(select(Episode)).scalars().all()) == 1
    assert len(db_session.execute(select(Event)).scalars().all()) == 1


def test_phone_stored_encrypted(client, sign_headers, db_session):
    body = json.dumps(EVENT).encode()
    client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    contact = db_session.execute(select(Contact)).scalar_one()
    # В базе — шифротекст, не открытый номер.
    assert "9001234567" not in contact.phone_enc
    # Но расшифровывается обратно в нормализованный номер.
    assert decrypt_phone(contact.phone_enc) == "79001234567"


def test_creating_event_writes_audit(client, sign_headers, db_session):
    body = json.dumps(EVENT).encode()
    client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    rows = db_session.execute(select(AuditEvent)).scalars().all()
    assert any(r.action == "mis.event.accepted" for r in rows)


def test_group_is_stable_across_events(db_session):
    """Один и тот же токен — одна группа, даже при новых событиях."""
    from app.schemas.events import ResultsReadyEvent
    from app.services.ingest_service import IngestService

    svc = IngestService(db_session)
    e1 = ResultsReadyEvent(**{**EVENT, "event_id": "a1"})
    r1 = svc.ingest(e1)
    e2 = ResultsReadyEvent(**{**EVENT, "event_id": "a2"})
    r2 = svc.ingest(e2)
    assert r1.group == r2.group


def test_bad_signature_is_401(client):
    body = json.dumps(EVENT).encode()
    r = client.post("/v1/mis/results-ready", content=body,
                    headers={"X-Rescan-Signature": "nope", "X-Rescan-Timestamp": "1"})
    assert r.status_code == 401


def test_missing_field_is_422(client, sign_headers):
    broken = {k: v for k, v in EVENT.items() if k != "ordering_doctor_id"}
    body = json.dumps(broken).encode()
    r = client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    assert r.status_code == 422


def test_patient_row_created(client, sign_headers, db_session):
    body = json.dumps(EVENT).encode()
    client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    patient = db_session.execute(select(Patient)).scalar_one()
    assert patient.patient_token == "pt-abc"
    assert patient.group in ("main", "control")
