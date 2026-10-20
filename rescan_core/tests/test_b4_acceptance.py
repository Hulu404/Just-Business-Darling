"""Приёмочные тесты B4 (очередь врача) по разделу «Контракты» задания 18.

Чёрный ящик: события приходят через HTTP с подписью (как в test_ingest.py), врач
работает через `/v1/doctor/...` с `X-Staff-Token`. Последствия смотрим в таблицах и
колонках, которые названы в контракте: episodes.status, episodes.queue_deadline_at,
clinics.step_options, steps, audit_events, outbox. Истечение срока — функция
`expire_overdue(session, now)` из контракта.

Формат clinics.step_options контракт не фиксирует. Здесь он принят таким же, как
список `options` в ответе `GET /v1/doctor/step-options`; если бэкенд выберет другой —
поправить одну функцию `configure_steps`.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.config import StaffToken, get_settings
from app.db.models import AuditEvent, Clinic, Doctor, Episode, Outbox, Step
from app.db.session import get_session
from app.main import app as fastapi_app
from app.services.group_service import Group, assign_group

DOCTOR = {"X-Staff-Token": "dev-doctor-token"}  # actor_id dev-doctor
ADMIN = {"X-Staff-Token": "dev-admin-token"}
OTHER_DOCTOR_TOKEN = "qa-other-doctor-token"
STRANGER_TOKEN = "qa-stranger-doctor-token"
PHONE = "+7 (900) 000-00-42"
PHONE_DIGITS = ("9000000042", "79000000042", "000-00-42")
OPTIONS = [
    {"code": "discuss", "title": "Обсудить на приёме"},
    {"code": "retest", "title": "Пересдать через несколько недель", "weeks": [2, 4, 8, 12]},
    {"code": "followup", "title": "Контроль у меня"},
]
DOCTOR_PATHS = {"/v1/doctor/queue", "/v1/doctor/step-options",
                "/v1/doctor/episodes/{episode_id}/step"}


# ---------- подготовка ----------

def configure_steps(session, options) -> None:
    value = None if options is None else json.dumps(options, ensure_ascii=False)
    for clinic in session.execute(select(Clinic)).scalars():
        clinic.step_options = value
    session.commit()


@pytest.fixture
def clinic(db_session):
    """Демо-клиника из conftest + врач сотрудника (external_id = actor_id) + шаги клиники."""
    clinic = db_session.execute(select(Clinic)).scalar_one()
    db_session.add_all([
        Doctor(clinic_id=clinic.id, external_id="dev-doctor", full_name="Синтетический Врач"),
        Doctor(clinic_id=clinic.id, external_id="qa-other", full_name="Другой Синтетический"),
    ])
    db_session.commit()
    configure_steps(db_session, OPTIONS)
    return clinic


@pytest.fixture
def staff_tokens(monkeypatch):
    tokens = dict(get_settings().staff_tokens)
    tokens[OTHER_DOCTOR_TOKEN] = StaffToken(role="doctor", actor_id="qa-other")
    tokens[STRANGER_TOKEN] = StaffToken(role="doctor", actor_id="qa-no-such-doctor")
    monkeypatch.setattr(get_settings(), "staff_tokens", tokens)


def token_in(group: Group, n: int = 0) -> str:
    found = (f"b4-pt-{i}" for i in range(5000) if assign_group(f"b4-pt-{i}") == group)
    for _ in range(n):
        next(found)
    return next(found)


def send(client, sign_headers, event_id: str, token: str, doctor: str = "dev-doctor") -> dict:
    body = json.dumps({
        "event_id": event_id, "branch_id": "br-1", "patient_token": token, "phone": PHONE,
        "ordering_doctor_id": doctor, "ready_at": "2026-10-14T09:00:00+03:00",
        "marketing_consent": True,
    }).encode()
    response = client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    assert response.status_code == 202, response.text
    return response.json()


def main_episode(client, sign_headers, n: int = 0, doctor: str = "dev-doctor") -> str:
    result = send(client, sign_headers, f"b4-evt-{doctor}-{n}", token_in(Group.MAIN, n), doctor)
    assert result["group"] == "main"
    return result["episode_id"]


def queue(client, headers=DOCTOR):
    return client.get("/v1/doctor/queue", headers=headers)


def mark(client, episode_id, body, headers=DOCTOR):
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    return client.post(f"/v1/doctor/episodes/{episode_id}/step", content=payload,
                       headers={**headers, "Content-Type": "application/json"})


def episode(session, episode_id) -> Episode:
    session.expire_all()
    return session.get(Episode, episode_id)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def no_phone(blob: str) -> None:
    for digits in PHONE_DIGITS:
        assert digits not in blob


# ---------- ingest: статус и срок ----------

def test_main_group_episode_waits_for_doctor_with_24h_deadline(client, sign_headers, db_session,
                                                              clinic):
    before = datetime.now(UTC)
    episode_id = main_episode(client, sign_headers)
    after = datetime.now(UTC)
    row = episode(db_session, episode_id)
    assert row.status == "awaiting_doctor"
    deadline = aware(row.queue_deadline_at)
    # срок от приёма события, не от ready_at (событие могло прийти с опозданием)
    assert before + timedelta(hours=24) - timedelta(seconds=2) <= deadline
    assert deadline <= after + timedelta(hours=24) + timedelta(seconds=2)


def test_control_group_episode_is_not_in_queue(client, sign_headers, db_session, clinic):
    result = send(client, sign_headers, "b4-control", token_in(Group.CONTROL))
    assert result["group"] == "control"
    assert episode(db_session, result["episode_id"]).status == "control"
    response = queue(client)
    assert response.status_code == 200
    assert response.json()["items"] == []


# ---------- GET /v1/doctor/queue ----------

def test_empty_queue_is_200_with_empty_items(client, clinic):
    response = queue(client)
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["server_time"]


def test_queue_lists_only_own_main_episodes_sorted_by_deadline(client, sign_headers, clinic,
                                                               staff_tokens):
    first = main_episode(client, sign_headers, 0)
    second = main_episode(client, sign_headers, 1)
    foreign = main_episode(client, sign_headers, 2, doctor="qa-other")
    send(client, sign_headers, "b4-control-q", token_in(Group.CONTROL))
    items = queue(client).json()["items"]
    assert [i["episode_id"] for i in items] == [first, second]
    deadlines = [i["queue_deadline_at"] for i in items]
    assert deadlines == sorted(deadlines)
    assert {"episode_id", "patient_token", "branch_name", "ready_at",
            "queue_deadline_at"} <= set(items[0])
    other = queue(client, {"X-Staff-Token": OTHER_DOCTOR_TOKEN}).json()["items"]
    assert [i["episode_id"] for i in other] == [foreign]


def test_queue_has_no_phone_name_or_health_data(client, sign_headers, clinic):
    main_episode(client, sign_headers)
    response = queue(client)
    no_phone(response.text)
    assert "Синтетический" not in response.text
    item_keys = set(response.json()["items"][0])
    assert not item_keys & {"phone", "full_name", "name", "patient_name", "result", "diagnosis",
                            "value", "abnormal"}


def test_queue_skips_expired_deadline_and_unsubscribed(client, sign_headers, db_session, clinic):
    overdue = main_episode(client, sign_headers, 0)
    unsubscribed = main_episode(client, sign_headers, 1)
    kept = main_episode(client, sign_headers, 2)
    db_session.execute(text("UPDATE episodes SET queue_deadline_at = :t WHERE id = :id"),
                       {"t": datetime.now(UTC) - timedelta(minutes=1), "id": overdue})
    patient_id = episode(db_session, unsubscribed).patient_id
    db_session.execute(text("UPDATE patients SET opted_out = :v WHERE id = :id"),
                       {"v": True, "id": patient_id})
    db_session.commit()
    assert [i["episode_id"] for i in queue(client).json()["items"]] == [kept]


def test_doctor_without_doctor_row_is_403(client, clinic, staff_tokens):
    assert queue(client, {"X-Staff-Token": STRANGER_TOKEN}).status_code == 403


def test_stopped_clinic_is_403(client, db_session, clinic):
    clinic.service_enabled = False
    db_session.commit()
    assert queue(client).status_code == 403


def test_clinic_without_step_options_is_503(client, db_session, clinic):
    configure_steps(db_session, None)
    response = queue(client)
    assert response.status_code == 503
    assert "список шагов клиники не настроен" in response.json()["detail"].lower()


@pytest.mark.parametrize("path", ["/v1/doctor/queue", "/v1/doctor/step-options"])
def test_doctor_endpoints_need_doctor_role(client, clinic, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Staff-Token": "nope"}).status_code == 401
    assert client.get(path, headers=ADMIN).status_code == 403


# ---------- GET /v1/doctor/step-options ----------

def test_step_options_come_from_clinic_settings(client, db_session, clinic):
    configure_steps(db_session, [OPTIONS[1], OPTIONS[2]])
    response = client.get("/v1/doctor/step-options", headers=DOCTOR)
    assert response.status_code == 200
    options = response.json()["options"]
    assert [o["code"] for o in options] == ["retest", "followup"]
    assert options[0]["title"] == "Пересдать через несколько недель"
    assert options[0]["weeks"] == [2, 4, 8, 12]


# ---------- POST /v1/doctor/episodes/{id}/step ----------

def test_mark_retest_creates_step_audit_and_outbox(client, sign_headers, db_session, clinic):
    episode_id = main_episode(client, sign_headers)
    response = mark(client, episode_id, {"code": "retest", "retest_weeks": 4})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["episode_id"] == episode_id
    assert body["status"] == "doctor_marked"
    assert body["step_id"]
    no_phone(response.text)
    assert episode(db_session, episode_id).status == "doctor_marked"

    step = db_session.get(Step, body["step_id"])
    doctor = db_session.execute(
        select(Doctor).where(Doctor.external_id == "dev-doctor")).scalar_one()
    assert step.episode_id == episode_id
    assert step.kind == "retest"
    assert step.set_by_doctor_id == doctor.id
    assert step.set_at is not None
    days = (aware(step.due_date) - aware(step.set_at)).days
    assert 27 <= days <= 28

    audit = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "doctor.step_marked")).scalars().all()
    assert len(audit) == 1
    assert audit[0].actor_id == "dev-doctor"
    assert audit[0].created_at is not None
    for row in db_session.execute(select(AuditEvent)).scalars():
        no_phone(row.payload or "")

    outbox = [o for o in db_session.execute(select(Outbox)).scalars()
              if "episode.doctor_marked" in (o.topic + " " + o.payload)]
    assert len(outbox) == 1
    assert episode_id in outbox[0].payload
    no_phone(outbox[0].payload)


@pytest.mark.parametrize("code", ["discuss", "followup"])
def test_mark_without_weeks(client, sign_headers, db_session, clinic, code):
    episode_id = main_episode(client, sign_headers)
    response = mark(client, episode_id, {"code": code})
    assert response.status_code == 201, response.text
    step = db_session.get(Step, response.json()["step_id"])
    assert step.kind == code
    assert step.due_date is None


def test_second_mark_is_409(client, sign_headers, clinic):
    episode_id = main_episode(client, sign_headers)
    assert mark(client, episode_id, {"code": "discuss"}).status_code == 201
    assert mark(client, episode_id, {"code": "followup"}).status_code == 409


def test_mark_after_deadline_is_409(client, sign_headers, db_session, clinic):
    episode_id = main_episode(client, sign_headers)
    db_session.execute(text("UPDATE episodes SET queue_deadline_at = :t WHERE id = :id"),
                       {"t": datetime.now(UTC) - timedelta(seconds=1), "id": episode_id})
    db_session.commit()
    assert mark(client, episode_id, {"code": "discuss"}).status_code == 409
    assert episode(db_session, episode_id).status == "awaiting_doctor"


def test_foreign_or_missing_episode_is_404(client, sign_headers, clinic, staff_tokens):
    foreign = main_episode(client, sign_headers, doctor="qa-other")
    first = mark(client, foreign, {"code": "discuss"})
    missing = mark(client, "00000000-0000-0000-0000-000000000000", {"code": "discuss"})
    assert first.status_code == missing.status_code == 404
    assert first.json() == missing.json()  # не раскрываем, что чужой эпизод существует


def test_control_episode_cannot_be_marked(client, sign_headers, clinic):
    result = send(client, sign_headers, "b4-control-mark", token_in(Group.CONTROL))
    assert mark(client, result["episode_id"], {"code": "discuss"}).status_code in (404, 409)


@pytest.mark.parametrize("body", [
    {"code": "unknown"},
    {"code": "retest", "retest_weeks": 3},
    {"code": "retest"},
    {"code": "discuss", "retest_weeks": 4},
    {"code": "discuss", "comment": "свободный текст"},
    {"code": "discuss", "episode_ids": ["a", "b"]},
    [{"code": "discuss"}],
])
def test_bad_body_is_422_and_changes_nothing(client, sign_headers, db_session, clinic, body):
    episode_id = main_episode(client, sign_headers)
    assert mark(client, episode_id, body).status_code == 422
    assert episode(db_session, episode_id).status == "awaiting_doctor"
    assert db_session.execute(select(Step)).scalars().all() == []


def test_code_disabled_in_clinic_is_422(client, sign_headers, db_session, clinic):
    configure_steps(db_session, [OPTIONS[0]])
    episode_id = main_episode(client, sign_headers)
    assert mark(client, episode_id, {"code": "followup"}).status_code == 422
    assert mark(client, episode_id, {"code": "discuss"}).status_code == 201


def test_admin_cannot_mark(client, sign_headers, clinic):
    episode_id = main_episode(client, sign_headers)
    assert mark(client, episode_id, {"code": "discuss"}, ADMIN).status_code == 403
    assert mark(client, episode_id, {"code": "discuss"}, {}).status_code == 401


def test_stopped_clinic_cannot_mark(client, sign_headers, db_session, clinic):
    episode_id = main_episode(client, sign_headers)
    clinic.service_enabled = False
    db_session.commit()
    assert mark(client, episode_id, {"code": "discuss"}).status_code == 403


def test_no_mass_marking_in_api():
    paths = fastapi_app.openapi()["paths"]
    doctor = {p for p in paths if p.startswith("/v1/doctor")}
    assert doctor == DOCTOR_PATHS
    assert set(paths["/v1/doctor/episodes/{episode_id}/step"]) == {"post"}
    for path in paths:
        assert not any(word in path.lower() for word in ("bulk", "batch", "mass", "all"))


# ---------- истечение срока ----------

def expire(db_session, now):
    from app.services.queue_service import expire_overdue
    result = expire_overdue(db_session, now)
    db_session.commit()
    return result


def test_expire_moves_overdue_to_default_message_once(client, sign_headers, db_session, clinic):
    overdue = main_episode(client, sign_headers, 0)
    marked = main_episode(client, sign_headers, 1)
    control = send(client, sign_headers, "b4-control-exp", token_in(Group.CONTROL))["episode_id"]
    assert mark(client, marked, {"code": "discuss"}).status_code == 201
    now = datetime.now(UTC) + timedelta(hours=24, minutes=1)
    expire(db_session, now)

    assert episode(db_session, overdue).status == "default_message"
    assert episode(db_session, marked).status == "doctor_marked"
    assert episode(db_session, control).status == "control"
    audit = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "queue.expired")).scalars().all()
    assert [a.actor_id for a in audit] == ["system"]
    no_phone(audit[0].payload or "")

    def defaults():
        return [o for o in db_session.execute(select(Outbox)).scalars()
                if "episode.default_message" in (o.topic + " " + o.payload)]
    assert len(defaults()) == 1
    assert overdue in defaults()[0].payload

    expire(db_session, now + timedelta(hours=1))  # повторный запуск ничего не меняет
    assert len(defaults()) == 1
    assert len(db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "queue.expired")).scalars().all()) == 1


def test_expire_before_deadline_changes_nothing(client, sign_headers, db_session, clinic):
    episode_id = main_episode(client, sign_headers)
    expire(db_session, datetime.now(UTC) + timedelta(hours=23))
    assert episode(db_session, episode_id).status == "awaiting_doctor"


def test_mark_after_expire_is_409(client, sign_headers, db_session, clinic):
    episode_id = main_episode(client, sign_headers)
    expire(db_session, datetime.now(UTC) + timedelta(hours=25))
    assert mark(client, episode_id, {"code": "discuss"}).status_code == 409
    assert episode(db_session, episode_id).status == "default_message"


# ---------- гонки (PostgreSQL) ----------

needs_postgres = pytest.mark.skipif(not os.environ.get("RESCAN_TEST_DATABASE_URL"),
                                    reason="гонки проверяются на PostgreSQL")


@pytest.fixture
def parallel(db_session):
    """Сессия на каждый запрос, как в бою: одновременные запросы идут разными соединениями."""
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)

    def per_request():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_session] = per_request
    yield factory
    fastapi_app.dependency_overrides.clear()


def run_together(*jobs):
    results: list = [None] * len(jobs)
    barrier = threading.Barrier(len(jobs))

    def runner(i, job):
        barrier.wait()
        results[i] = job()

    threads = [threading.Thread(target=runner, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


@needs_postgres
def test_two_simultaneous_marks_give_one_result(sign_headers, db_session, clinic, parallel):
    with TestClient(fastapi_app) as c1, TestClient(fastapi_app) as c2:
        episode_id = main_episode(c1, sign_headers)
        codes = run_together(lambda: mark(c1, episode_id, {"code": "discuss"}).status_code,
                             lambda: mark(c2, episode_id, {"code": "followup"}).status_code)
    assert sorted(codes) == [201, 409]
    steps = db_session.execute(select(Step).where(Step.episode_id == episode_id)).scalars().all()
    assert len(steps) == 1
    assert len(db_session.execute(select(AuditEvent).where(
        AuditEvent.action == "doctor.step_marked")).scalars().all()) == 1


@needs_postgres
def test_mark_and_expire_together_give_one_result(sign_headers, db_session, clinic, parallel):
    with TestClient(fastapi_app) as c1:
        episode_id = main_episode(c1, sign_headers)

        def expire_job():
            session = parallel()
            try:
                expire(session, datetime.now(UTC) + timedelta(hours=25))
            finally:
                session.close()
            return "expired"

        code, _ = run_together(lambda: mark(c1, episode_id, {"code": "discuss"}).status_code,
                               expire_job)
    status = episode(db_session, episode_id).status
    rows = db_session.execute(select(Outbox)).scalars()
    outbox = " ".join(o.topic + " " + o.payload for o in rows)
    if code == 201:
        assert status == "doctor_marked"
        assert "episode.default_message" not in outbox
    else:
        assert code == 409
        assert status == "default_message"
        assert "episode.doctor_marked" not in outbox
