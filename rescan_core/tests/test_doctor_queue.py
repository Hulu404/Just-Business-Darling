"""B4: очередь врача, список шагов и отметка шага по одному эпизоду."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import (
    AuditEvent,
    Branch,
    Clinic,
    Doctor,
    Episode,
    Outbox,
    Patient,
    Step,
)
from app.main import app as fastapi_app
from app.schemas.queue import StepMarkRequest
from app.services.group_service import Group, assign_group
from app.services.queue_service import QueueService, expire_overdue
from tests.test_ingest import EVENT

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = {"X-Staff-Token": "dev-doctor-token"}
ADMIN = {"X-Staff-Token": "dev-admin-token"}
ALL_OPTIONS = [
    {"code": "discuss", "title": "Обсудить на приёме"},
    {"code": "retest", "title": "Пересдать через несколько недель", "weeks": [2, 4, 8, 12]},
    {"code": "followup", "title": "Прийти ко мне на контроль"},
]
QUEUE_KEYS = {"episode_id", "patient_token", "branch_name", "ready_at", "queue_deadline_at"}


def utc(value: datetime | None) -> datetime | None:
    """SQLite возвращает время без пояса: в rescan_core всё хранится в UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def token_in(group: Group, prefix: str) -> str:
    return next(f"{prefix}-{i}" for i in range(1000) if assign_group(f"{prefix}-{i}") == group)


@pytest.fixture
def clinic(db_session) -> Clinic:
    clinic = db_session.execute(select(Clinic)).scalar_one()
    clinic.step_options = json.dumps(ALL_OPTIONS, ensure_ascii=False)
    db_session.commit()
    return clinic


@pytest.fixture
def doctor(db_session, clinic) -> Doctor:
    doctor = Doctor(clinic_id=clinic.id, external_id="dev-doctor", full_name="Демо Врач Очереди")
    db_session.add(doctor)
    db_session.commit()
    return doctor


@pytest.fixture
def other_doctor(db_session, clinic) -> Doctor:
    return db_session.execute(select(Doctor).where(Doctor.external_id == "doc-1")).scalar_one()


@pytest.fixture
def make_episode(db_session, clinic):
    counter = iter(range(1000))

    def _make(doctor: Doctor, *, status: str = "awaiting_doctor", group: str = "main",
              deadline: datetime | None = None, opted_out: bool = False,
              branch_name: str | None = "Демо-филиал") -> Episode:
        index = next(counter)
        branch = Branch(clinic_id=clinic.id, external_id=f"br-q-{index}", name=branch_name)
        patient = Patient(clinic_id=clinic.id, patient_token=f"pt-q-{index}", group=group,
                          opted_out=opted_out)
        db_session.add_all([branch, patient])
        db_session.flush()
        episode = Episode(
            patient_id=patient.id, branch_id=branch.id, ordering_doctor_id=doctor.id,
            group=group, status=status, ready_at=datetime(2026, 10, 18, 9, tzinfo=UTC),
            queue_deadline_at=(deadline if deadline is not None
                               else datetime.now(UTC) + timedelta(hours=12)),
        )
        db_session.add(episode)
        db_session.commit()
        return episode

    return _make


def mark(client, episode_id: str, body, headers=DOCTOR):
    return client.post(f"/v1/doctor/episodes/{episode_id}/step", json=body, headers=headers)


def count(session: Session, model) -> int:
    session.expire_all()
    return len(session.execute(select(model)).scalars().all())


# --- доступ ---------------------------------------------------------------

@pytest.mark.parametrize("path", ["/v1/doctor/queue", "/v1/doctor/step-options"])
def test_doctor_endpoints_require_doctor_role(client, doctor, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Staff-Token": "unknown"}).status_code == 401
    assert client.get(path, headers=ADMIN).status_code == 403


def test_mark_requires_doctor_role(client, doctor, make_episode):
    episode = make_episode(doctor)
    assert mark(client, episode.id, {"code": "discuss"}, headers={}).status_code == 401
    assert mark(client, episode.id, {"code": "discuss"}, headers=ADMIN).status_code == 403


def test_staff_without_doctor_record_is_forbidden(client, clinic, other_doctor, make_episode):
    episode = make_episode(other_doctor)
    assert client.get("/v1/doctor/queue", headers=DOCTOR).status_code == 403
    assert client.get("/v1/doctor/step-options", headers=DOCTOR).status_code == 403
    assert mark(client, episode.id, {"code": "discuss"}).status_code == 403


def test_doctor_from_other_clinic_is_forbidden(client, db_session, clinic, monkeypatch):
    other = Clinic(name="Демо чужая клиника", service_enabled=True,
                   step_options=clinic.step_options)
    db_session.add(other)
    db_session.flush()
    db_session.add(Doctor(clinic_id=other.id, external_id="dev-doctor", full_name="Демо"))
    db_session.commit()
    # Клиник две и MIS_CLINIC_ID не задан: клиника интеграции не определена.
    assert client.get("/v1/doctor/queue", headers=DOCTOR).status_code == 503
    monkeypatch.setattr(get_settings(), "mis_clinic_id", clinic.id)
    assert client.get("/v1/doctor/queue", headers=DOCTOR).status_code == 403


@pytest.mark.parametrize("path", ["/v1/doctor/queue", "/v1/doctor/step-options"])
def test_stopped_clinic_is_forbidden(client, db_session, clinic, doctor, path):
    clinic.service_enabled = False
    db_session.commit()
    assert client.get(path, headers=DOCTOR).status_code == 403


def test_stopped_clinic_blocks_mark(client, db_session, clinic, doctor, make_episode):
    episode = make_episode(doctor)
    clinic.service_enabled = False
    db_session.commit()
    assert mark(client, episode.id, {"code": "discuss"}).status_code == 403
    assert count(db_session, Step) == 0


@pytest.mark.parametrize("raw", [None, "", "[]"])
def test_missing_step_options_is_503(client, db_session, clinic, doctor, make_episode, raw):
    episode = make_episode(doctor)
    clinic.step_options = raw
    db_session.commit()
    for response in (
        client.get("/v1/doctor/queue", headers=DOCTOR),
        client.get("/v1/doctor/step-options", headers=DOCTOR),
        mark(client, episode.id, {"code": "discuss"}),
    ):
        assert response.status_code == 503
        assert response.json()["detail"] == "Список шагов клиники не настроен."
    assert count(db_session, Step) == 0


@pytest.mark.parametrize("raw", [
    "not json",
    '{"code": "discuss"}',
    '[{"code": "unknown", "title": "Демо"}]',
    '[{"code": "discuss", "title": ""}]',
    '[{"code": "retest", "title": "Демо"}]',
    '[{"code": "retest", "title": "Демо", "weeks": []}]',
    '[{"code": "retest", "title": "Демо", "weeks": [0]}]',
    '[{"code": "retest", "title": "Демо", "weeks": [53]}]',
    '[{"code": "retest", "title": "Демо", "weeks": [1000000]}]',
    '[{"code": "discuss", "title": "Демо", "weeks": [2]}]',
    '[{"code": "discuss", "title": "Демо"}, {"code": "discuss", "title": "Ещё"}]',
])
def test_broken_step_options_are_not_configured(client, db_session, clinic, doctor, raw):
    clinic.step_options = raw
    db_session.commit()
    assert client.get("/v1/doctor/step-options", headers=DOCTOR).status_code == 503


# --- очередь --------------------------------------------------------------

def test_empty_queue(client, doctor):
    response = client.get("/v1/doctor/queue", headers=DOCTOR)
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert datetime.fromisoformat(body["server_time"]).tzinfo is not None


def test_queue_has_only_own_open_main_episodes_sorted(
    client, doctor, other_doctor, make_episode,
):
    now = datetime.now(UTC)
    late = make_episode(doctor, deadline=now + timedelta(hours=20))
    soon = make_episode(doctor, deadline=now + timedelta(hours=1), branch_name=None)
    make_episode(other_doctor)
    make_episode(doctor, status="control", group="control")
    make_episode(doctor, status="doctor_marked")
    make_episode(doctor, status="default_message")
    make_episode(doctor, deadline=now - timedelta(minutes=1))
    make_episode(doctor, opted_out=True)

    response = client.get("/v1/doctor/queue", headers=DOCTOR)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["episode_id"] for item in items] == [soon.id, late.id]
    assert all(set(item) == QUEUE_KEYS for item in items)
    assert items[0]["branch_name"] is None
    assert items[1]["branch_name"] == "Демо-филиал"
    assert items[1]["patient_token"] == "pt-q-0"
    deadline = datetime.fromisoformat(items[1]["queue_deadline_at"])
    assert abs(deadline - (now + timedelta(hours=20))) < timedelta(seconds=1)


def test_ingested_event_reaches_queue_without_personal_data(
    client, sign_headers, db_session, doctor,
):
    token = token_in(Group.MAIN, "pt-queue")
    event = {**EVENT, "patient_token": token, "ordering_doctor_id": "dev-doctor"}
    body = json.dumps(event).encode()
    before = datetime.now(UTC)
    assert client.post("/v1/mis/results-ready", content=body,
                       headers=sign_headers(body)).status_code == 202
    after = datetime.now(UTC)

    response = client.get("/v1/doctor/queue", headers=DOCTOR)
    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert item["patient_token"] == token
    deadline = datetime.fromisoformat(item["queue_deadline_at"])
    assert before + timedelta(hours=24) <= deadline <= after + timedelta(hours=24)
    for private in ("9001234567", EVENT["phone"], doctor.full_name, "Тестовый Врач"):
        assert private not in response.text


# --- список шагов ---------------------------------------------------------

def test_step_options_are_clinic_subset(client, db_session, clinic, doctor):
    clinic.step_options = json.dumps(ALL_OPTIONS[1:], ensure_ascii=False)
    db_session.commit()
    response = client.get("/v1/doctor/step-options", headers=DOCTOR)
    assert response.status_code == 200
    assert response.json() == {"options": [
        {"code": "retest", "title": "Пересдать через несколько недель", "weeks": [2, 4, 8, 12]},
        {"code": "followup", "title": "Прийти ко мне на контроль"},
    ]}


# --- отметка шага ---------------------------------------------------------

def test_mark_retest_writes_step_audit_outbox(client, db_session, doctor, make_episode):
    episode = make_episode(doctor)
    before = datetime.now(UTC)
    response = mark(client, episode.id, {"code": "retest", "retest_weeks": 4})
    after = datetime.now(UTC)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"episode_id", "step_id", "status"}
    assert body["episode_id"] == episode.id
    assert body["status"] == "doctor_marked"

    db_session.expire_all()
    step = db_session.execute(select(Step)).scalar_one()
    assert step.id == body["step_id"]
    assert step.episode_id == episode.id
    assert step.kind == "retest"
    assert step.set_by_doctor_id == doctor.id
    set_at = utc(step.set_at)
    assert set_at is not None and before <= set_at <= after
    assert utc(step.due_date) == set_at + timedelta(weeks=4)
    assert db_session.get(Episode, episode.id).status == "doctor_marked"

    (entry,) = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "doctor.step_marked")).scalars().all()
    assert entry.actor_id == "dev-doctor"
    assert entry.role == "doctor"
    assert entry.entity_id == episode.id
    assert "phone" not in (entry.payload or "")

    (job,) = db_session.execute(select(Outbox)).scalars().all()
    assert job.topic == "episode.doctor_marked"
    payload = json.loads(job.payload)
    assert payload["episode_id"] == episode.id
    assert payload["step_id"] == step.id
    assert payload["code"] == "retest"
    assert payload["retest_weeks"] == 4

    assert client.get("/v1/doctor/queue", headers=DOCTOR).json()["items"] == []


@pytest.mark.parametrize("code", ["discuss", "followup"])
def test_mark_without_weeks_has_no_due_date(client, db_session, doctor, make_episode, code):
    episode = make_episode(doctor)
    assert mark(client, episode.id, {"code": code}).status_code == 201
    db_session.expire_all()
    step = db_session.execute(select(Step)).scalar_one()
    assert step.kind == code
    assert step.due_date is None


def test_ingested_episode_mark_has_no_phone_in_audit(client, sign_headers, db_session, doctor):
    token = token_in(Group.MAIN, "pt-audit")
    body = json.dumps({**EVENT, "patient_token": token,
                       "ordering_doctor_id": "dev-doctor"}).encode()
    episode_id = client.post("/v1/mis/results-ready", content=body,
                             headers=sign_headers(body)).json()["episode_id"]
    response = mark(client, episode_id, {"code": "discuss"})
    assert response.status_code == 201
    assert "9001234567" not in response.text
    db_session.expire_all()
    for entry in db_session.execute(select(AuditEvent)).scalars():
        assert "9001234567" not in (entry.payload or "")
    for job in db_session.execute(select(Outbox)).scalars():
        assert "9001234567" not in job.payload


def test_foreign_and_missing_episode_is_404(client, db_session, doctor, other_doctor,
                                            make_episode):
    foreign = make_episode(other_doctor)
    for episode_id in (foreign.id, "00000000-0000-0000-0000-000000000000"):
        response = mark(client, episode_id, {"code": "discuss"})
        assert response.status_code == 404
    assert count(db_session, Step) == 0
    db_session.expire_all()
    assert db_session.get(Episode, foreign.id).status == "awaiting_doctor"


@pytest.mark.parametrize("kwargs", [
    {"status": "control", "group": "control"},
    {"opted_out": True},
])
def test_episode_outside_queue_is_404(client, db_session, doctor, make_episode, kwargs):
    episode = make_episode(doctor, **kwargs)
    assert mark(client, episode.id, {"code": "discuss"}).status_code == 404
    assert count(db_session, Step) == 0


def test_second_mark_is_409(client, db_session, doctor, make_episode):
    episode = make_episode(doctor)
    assert mark(client, episode.id, {"code": "discuss"}).status_code == 201
    assert mark(client, episode.id, {"code": "followup"}).status_code == 409
    assert count(db_session, Step) == 1
    assert count(db_session, Outbox) == 1


@pytest.mark.parametrize("kwargs", [
    {"status": "default_message"},
    {"deadline": datetime(2026, 1, 1, tzinfo=UTC)},
])
def test_expired_episode_is_409(client, db_session, doctor, make_episode, kwargs):
    episode = make_episode(doctor, **kwargs)
    assert mark(client, episode.id, {"code": "discuss"}).status_code == 409
    assert count(db_session, Step) == 0
    assert count(db_session, Outbox) == 0


@pytest.mark.parametrize("body", [
    {"code": "unknown"},
    {"code": "retest"},
    {"code": "retest", "retest_weeks": 3},
    {"code": "retest", "retest_weeks": "4"},
    {"code": "retest", "retest_weeks": True},
    {"code": "discuss", "retest_weeks": 4},
    {"code": "discuss", "retest_weeks": None},
    {"code": "followup", "retest_weeks": None},
    {"code": "discuss", "comment": "synthetic"},
    {"code": "discuss", "episode_ids": ["x"]},
    {},
    [{"code": "discuss"}],
    [],
])
def test_invalid_body_is_422(client, db_session, doctor, make_episode, body):
    episode = make_episode(doctor)
    assert mark(client, episode.id, body).status_code == 422
    assert count(db_session, Step) == 0
    db_session.expire_all()
    assert db_session.get(Episode, episode.id).status == "awaiting_doctor"


def test_code_disabled_in_clinic_is_422(client, db_session, clinic, doctor, make_episode):
    clinic.step_options = json.dumps(ALL_OPTIONS[:2], ensure_ascii=False)
    db_session.commit()
    episode = make_episode(doctor)
    assert mark(client, episode.id, {"code": "followup"}).status_code == 422
    assert mark(client, episode.id, {"code": "discuss"}).status_code == 201


def test_api_has_no_bulk_marking():
    paths = fastapi_app.openapi()["paths"]
    doctor_paths = {path: set(ops) for path, ops in paths.items() if path.startswith("/v1/doctor")}
    assert doctor_paths == {
        "/v1/doctor/queue": {"get"},
        "/v1/doctor/step-options": {"get"},
        "/v1/doctor/episodes/{episode_id}/step": {"post"},
    }
    schema = StepMarkRequest.model_json_schema()
    assert set(schema["properties"]) == {"code", "retest_weeks"}
    assert schema.get("additionalProperties") is False


# --- гонки ----------------------------------------------------------------

def run_parallel(*calls):
    barrier = Barrier(len(calls))

    def run(call):
        barrier.wait(timeout=15)
        try:
            return call()
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=len(calls)) as executor:
        return list(executor.map(run, calls))


def test_parallel_marks_give_one_result(db_session, empty_engine, doctor, make_episode):
    episode = make_episode(doctor)
    now = datetime.now(UTC)

    def marker(code: str):
        def _call():
            with Session(empty_engine, expire_on_commit=False) as session:
                result = QueueService(session).mark_step(
                    "dev-doctor", episode.id, StepMarkRequest(code=code), now=now)
                return result.status
        return _call

    results = run_parallel(marker("discuss"), marker("followup"))
    assert sorted(map(str, results)) == ["409", "doctor_marked"]
    assert count(db_session, Step) == 1
    assert count(db_session, Outbox) == 1
    assert db_session.get(Episode, episode.id).status == "doctor_marked"


def test_mark_and_expire_give_one_result(db_session, empty_engine, doctor, make_episode):
    deadline = datetime.now(UTC) + timedelta(hours=1)
    episode = make_episode(doctor, deadline=deadline)

    def marker():
        with Session(empty_engine, expire_on_commit=False) as session:
            return QueueService(session).mark_step(
                "dev-doctor", episode.id, StepMarkRequest(code="discuss"),
                now=deadline - timedelta(seconds=1)).status

    def expirer():
        with Session(empty_engine, expire_on_commit=False) as session:
            return expire_overdue(session, deadline + timedelta(seconds=1))

    marked, expired = run_parallel(marker, expirer)
    db_session.expire_all()
    status = db_session.get(Episode, episode.id).status
    jobs = db_session.execute(select(Outbox)).scalars().all()
    assert len(jobs) == 1
    if marked == "doctor_marked":
        assert expired == 0
        assert status == "doctor_marked"
        assert jobs[0].topic == "episode.doctor_marked"
        assert count(db_session, Step) == 1
    else:
        assert marked == 409
        assert expired == 1
        assert status == "default_message"
        assert jobs[0].topic == "episode.default_message"
        assert count(db_session, Step) == 0


# --- приём события: статус и срок ----------------------------------------

def test_ingest_sets_awaiting_doctor_and_deadline_for_main(db_session):
    from app.schemas.events import ResultsReadyEvent
    from app.services.ingest_service import IngestService

    token = token_in(Group.MAIN, "pt-main")
    before = datetime.now(UTC)
    result = IngestService(db_session).ingest(
        ResultsReadyEvent(**{**EVENT, "patient_token": token}))
    after = datetime.now(UTC)
    episode = db_session.get(Episode, result.episode_id)
    assert episode.status == "awaiting_doctor"
    deadline = utc(episode.queue_deadline_at)
    # От времени приёма, не от ready_at: событие могло прийти с опозданием.
    assert deadline is not None
    assert before + timedelta(hours=24) <= deadline <= after + timedelta(hours=24)


def test_ingest_sets_control_status_without_deadline(db_session):
    from app.schemas.events import ResultsReadyEvent
    from app.services.ingest_service import IngestService

    token = token_in(Group.CONTROL, "pt-control")
    result = IngestService(db_session).ingest(
        ResultsReadyEvent(**{**EVENT, "patient_token": token}))
    assert result.group == "control"
    episode = db_session.get(Episode, result.episode_id)
    assert episode.status == "control"
    assert episode.queue_deadline_at is None


# --- демо-данные и миграция -----------------------------------------------

def test_seed_demo_configures_queue(empty_engine, monkeypatch):
    from app.db.base import Base
    from scripts import seed_demo

    Base.metadata.create_all(empty_engine)
    factory = sessionmaker(bind=empty_engine, expire_on_commit=False)

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(seed_demo, "session_scope", scope)
    seed_demo.seed()
    seed_demo.seed()
    with factory() as session:
        clinic = session.execute(select(Clinic)).scalar_one()
        options = json.loads(clinic.step_options)
        assert [item["code"] for item in options] == ["discuss", "retest", "followup"]
        doctors = session.execute(
            select(Doctor).where(Doctor.external_id == "dev-doctor")).scalars().all()
        assert len(doctors) == 1
        assert doctors[0].clinic_id == clinic.id
        assert QueueService(session).step_options("dev-doctor").options


def test_migration_adds_queue_columns_to_existing_data(empty_engine):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "20261017_secure_ingest")
        conn.execute(text(
            "INSERT INTO clinics (id, name, service_enabled, created_at, updated_at) "
            "VALUES ('c1', 'Демо', :on, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"on": True})
        conn.execute(text(
            "INSERT INTO patients (id, clinic_id, patient_token, opted_out, created_at, "
            "updated_at) VALUES ('p1', 'c1', 'demo-token', :off, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)"), {"off": False})
        conn.execute(text(
            "INSERT INTO episodes (id, patient_id, \"group\", status, ready_at, created_at, "
            "updated_at) VALUES ('e1', 'p1', 'main', 'open', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        inspector = inspect(conn)
        assert "queue_deadline_at" in {c["name"] for c in inspector.get_columns("episodes")}
        assert "step_options" in {c["name"] for c in inspector.get_columns("clinics")}
        row = conn.execute(text(
            "SELECT status, queue_deadline_at FROM episodes WHERE id = 'e1'")).one()
        assert row.status == "open"
        assert row.queue_deadline_at is None
        assert conn.execute(text("SELECT step_options FROM clinics")).scalar_one() is None


@pytest.mark.parametrize("body", [
    {"code": "discuss", "phone": "+79990000000"},
    {"code": "+79990000000"},
    [{"code": "discuss", "phone": "+79990000000"}],
])
def test_422_does_not_echo_request_body(client, doctor, make_episode, body):
    episode = make_episode(doctor)
    response = mark(client, episode.id, body)
    assert response.status_code == 422
    assert "79990000000" not in response.text
    assert "input" not in response.text
    assert response.json() == {"detail": "Некорректная отметка шага. Проверьте поля запроса."}


def test_malformed_json_is_anonymous_422(client, doctor, make_episode):
    episode = make_episode(doctor)
    response = client.post(f"/v1/doctor/episodes/{episode.id}/step",
                           content=b'{"code": "+79990000000"', headers={
                               **DOCTOR, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert "79990000000" not in response.text


def test_huge_weeks_in_settings_never_500(client, db_session, clinic, doctor, make_episode):
    clinic.step_options = '[{"code": "retest", "title": "Демо", "weeks": [1000000]}]'
    db_session.commit()
    episode = make_episode(doctor)
    response = mark(client, episode.id, {"code": "retest", "retest_weeks": 1000000})
    assert response.status_code == 503
    assert count(db_session, Step) == 0


def test_max_weeks_in_settings_is_accepted(client, db_session, clinic, doctor, make_episode):
    clinic.step_options = '[{"code": "retest", "title": "Демо", "weeks": [1, 52]}]'
    db_session.commit()
    episode = make_episode(doctor)
    assert mark(client, episode.id, {"code": "retest", "retest_weeks": 52}).status_code == 201
