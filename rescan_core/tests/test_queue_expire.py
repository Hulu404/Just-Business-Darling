"""B4: истечение 24 часов без отметки врача → стандартное сообщение."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Branch, Clinic, Doctor, Episode, Outbox, Patient
from app.schemas.queue import StepMarkRequest
from app.services.queue_service import QueueService, expire_overdue

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
OPTIONS = '[{"code": "discuss", "title": "Обсудить на приёме"}]'


@pytest.fixture
def doctor(db_session) -> Doctor:
    clinic = db_session.execute(select(Clinic)).scalar_one()
    clinic.step_options = OPTIONS
    doctor = Doctor(clinic_id=clinic.id, external_id="dev-doctor", full_name="Демо Врач")
    db_session.add(doctor)
    db_session.commit()
    return doctor


@pytest.fixture
def episode_at(db_session, doctor):
    counter = iter(range(1000))

    def _make(deadline: datetime | None, *, status: str = "awaiting_doctor",
              group: str = "main") -> Episode:
        index = next(counter)
        branch = Branch(clinic_id=doctor.clinic_id, external_id=f"br-x-{index}")
        patient = Patient(clinic_id=doctor.clinic_id, patient_token=f"pt-x-{index}",
                          group=group)
        db_session.add_all([branch, patient])
        db_session.flush()
        episode = Episode(patient_id=patient.id, branch_id=branch.id,
                          ordering_doctor_id=doctor.id, group=group, status=status,
                          ready_at=NOW - timedelta(days=1), queue_deadline_at=deadline)
        db_session.add(episode)
        db_session.commit()
        return episode

    return _make


def statuses(session: Session) -> dict[str, str]:
    session.expire_all()
    return {row.id: row.status for row in session.execute(select(Episode)).scalars()}


def test_overdue_episodes_get_default_message(db_session, episode_at):
    overdue = episode_at(NOW - timedelta(minutes=1))
    on_time = episode_at(NOW)  # граница: срок ровно сейчас уже истёк
    future = episode_at(NOW + timedelta(minutes=1))
    marked = episode_at(NOW - timedelta(hours=1), status="doctor_marked")
    control = episode_at(None, status="control", group="control")

    assert expire_overdue(db_session, NOW) == 2

    assert statuses(db_session) == {
        overdue.id: "default_message",
        on_time.id: "default_message",
        future.id: "awaiting_doctor",
        marked.id: "doctor_marked",
        control.id: "control",
    }
    jobs = db_session.execute(select(Outbox)).scalars().all()
    assert {job.topic for job in jobs} == {"episode.default_message"}
    assert {json.loads(job.payload)["episode_id"] for job in jobs} == {overdue.id, on_time.id}
    entries = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "queue.expired")).scalars().all()
    assert {entry.entity_id for entry in entries} == {overdue.id, on_time.id}
    assert {entry.actor_id for entry in entries} == {"system"}
    assert {entry.role for entry in entries} == {"system"}


def test_second_run_changes_nothing(db_session, episode_at):
    episode_at(NOW - timedelta(hours=2))
    assert expire_overdue(db_session, NOW) == 1
    assert expire_overdue(db_session, NOW) == 0
    assert expire_overdue(db_session, NOW + timedelta(days=3)) == 0
    assert len(db_session.execute(select(Outbox)).scalars().all()) == 1
    assert len(db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "queue.expired")).scalars().all()) == 1


def test_time_is_a_parameter_and_naive_time_means_utc(db_session, episode_at):
    episode = episode_at(NOW + timedelta(hours=24))
    assert expire_overdue(db_session, NOW + timedelta(hours=23, minutes=59)) == 0
    moscow = NOW.astimezone(datetime.fromisoformat("2026-01-01T00:00:00+03:00").tzinfo)
    assert expire_overdue(db_session, moscow + timedelta(hours=23)) == 0
    naive = (NOW + timedelta(hours=24)).replace(tzinfo=None)
    assert expire_overdue(db_session, naive) == 1
    assert statuses(db_session)[episode.id] == "default_message"


def test_expired_episode_cannot_be_marked(db_session, episode_at):
    episode = episode_at(NOW + timedelta(hours=1))
    assert expire_overdue(db_session, NOW + timedelta(hours=2)) == 1
    with pytest.raises(HTTPException) as exc:
        QueueService(db_session).mark_step(
            "dev-doctor", episode.id, StepMarkRequest(code="discuss"), now=NOW)
    assert exc.value.status_code == 409


def test_script_expires_with_current_time(db_session, episode_at, monkeypatch, capsys):
    from scripts import expire_queue

    episode = episode_at(datetime.now(UTC) - timedelta(seconds=1))
    episode_at(datetime.now(UTC) + timedelta(hours=1))

    @contextmanager
    def scope():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(expire_queue, "session_scope", scope)
    assert expire_queue.main() == 0
    assert "1" in capsys.readouterr().out
    assert statuses(db_session)[episode.id] == "default_message"
