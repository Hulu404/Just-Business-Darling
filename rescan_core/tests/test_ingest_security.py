"""Регрессии ревью: ПДн, отключение, длинные ID, конкурентные запросы."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    AuditEvent,
    Branch,
    Clinic,
    Consent,
    Contact,
    Doctor,
    Episode,
    Event,
    Patient,
)
from app.schemas.events import ResultsReadyEvent
from app.services import audit
from app.services.ingest_service import IngestService
from tests.test_ingest import EVENT


def post_event(client, sign_headers, event=None):
    body = json.dumps(EVENT if event is None else event).encode()
    return client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))


def test_phone_is_absent_from_event_and_audit(client, sign_headers, db_session):
    assert post_event(client, sign_headers).status_code == 202
    stored = db_session.execute(select(Event)).scalar_one()
    assert stored.raw_payload is None
    entries = db_session.execute(select(AuditEvent)).scalars().all()
    assert all(EVENT["phone"] not in (entry.payload or "") for entry in entries)


def test_raw_service_argument_is_never_persisted(db_session):
    body = json.dumps({**EVENT, "diagnosis": "synthetic-private-text"}).encode()
    IngestService(db_session).ingest(ResultsReadyEvent(**EVENT), raw=body)
    assert db_session.execute(select(Event)).scalar_one().raw_payload is None


def test_unknown_fields_rejected_without_echoing_private_data(client, sign_headers, db_session):
    response = post_event(client, sign_headers, {**EVENT, "diagnosis": "synthetic-private-text"})
    assert response.status_code == 422
    assert "synthetic-private-text" not in response.text
    assert EVENT["phone"] not in response.text
    assert db_session.execute(select(Event)).first() is None


def test_disabled_clinic_creates_nothing(client, sign_headers, db_session):
    db_session.execute(select(Clinic)).scalar_one().service_enabled = False
    db_session.commit()
    assert post_event(client, sign_headers).status_code == 403
    for model in (Event, Patient, Contact, Episode, Consent, AuditEvent):
        assert db_session.execute(select(model)).first() is None


def test_multiple_clinics_require_explicit_binding(client, sign_headers, db_session, monkeypatch):
    target = Clinic(name="Демо вторая клиника", service_enabled=True)
    db_session.add(target)
    db_session.commit()
    assert post_event(client, sign_headers).status_code == 503
    monkeypatch.setattr(get_settings(), "mis_clinic_id", target.id)
    assert post_event(client, sign_headers).status_code == 202
    assert db_session.execute(select(Patient)).scalar_one().clinic_id == target.id


def test_max_length_event_id_is_committed(client, sign_headers, db_session):
    long_id = "e" * 128
    response = post_event(client, sign_headers, {**EVENT, "event_id": long_id})
    assert response.status_code == 202
    assert db_session.execute(select(AuditEvent)).scalar_one().entity_id == long_id
    assert db_session.execute(select(Event)).scalar_one().event_id == long_id


@pytest.mark.parametrize("same_event", [True, False])
def test_parallel_events_share_patient_and_contact(db_session, empty_engine, same_event):
    # Новые филиал, врач и пациент: гонка должна покрывать все справочники.
    barrier = Barrier(4)

    def ingest(index):
        event = ResultsReadyEvent(**{
            **EVENT, "event_id": "parallel" if same_event else f"parallel-{index}",
            "ordering_doctor_id": "new-doctor",
        })
        with Session(empty_engine, expire_on_commit=False) as session:
            barrier.wait(timeout=15)
            return IngestService(session).ingest(event)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(ingest, range(4)))
    created = [result for result in results if result.status == "created"]
    assert len(created) == (1 if same_event else 4)
    for model in (Patient, Contact, Branch):
        assert len(db_session.execute(select(model)).scalars().all()) == 1
    assert len(db_session.execute(select(Doctor).where(Doctor.external_id == "new-doctor"))
               .scalars().all()) == 1
    assert len(db_session.execute(select(Episode)).scalars().all()) == len(created)
    assert len(db_session.execute(select(Event)).scalars().all()) == len(created)
    if same_event:
        assert len({result.episode_id for result in results}) == 1
    assert len({row.group for row in db_session.execute(select(Episode)).scalars()}) == 1


def test_failure_rolls_back_claim_and_retry_succeeds(db_session, empty_engine, monkeypatch):
    original = audit.record

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(RuntimeError), Session(empty_engine) as session:
        IngestService(session).ingest(ResultsReadyEvent(**EVENT))
    for model in (Event, Patient, Episode, Contact, Consent):
        assert db_session.execute(select(model)).first() is None
    db_session.rollback()
    monkeypatch.setattr(audit, "record", original)
    assert IngestService(db_session).ingest(ResultsReadyEvent(**EVENT)).status == "created"
