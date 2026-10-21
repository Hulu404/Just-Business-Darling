"""B6: API пациента по личной ссылке — сессия, согласие, выбор, форматы, заявка."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditEvent,
    Clinic,
    Consent,
    Doctor,
    Episode,
    Format,
    Goal,
    GoalDoctor,
    Outbox,
    Patient,
    PatientLink,
    Request,
    Step,
)
from app.db.session import get_session
from app.main import app as fastapi_app
from app.security.patient_link import hash_token, new_token
from app.services.group_service import Group, assign_group
from app.services.patient_service import PatientService, issue_link
from tests.test_ingest import EVENT

SETTINGS = {
    "phone": "+7 000 000-00-00",
    "privacy_url": "https://example-clinic.ru/privacy",
    "timezone": "Europe/Moscow",
    "branches": [
        {"code": "discuss", "title": "Обсудить анализы с врачом", "hint": "Приём или онлайн"},
        {"code": "retest", "title": "Записаться на пересдачу", "hint": "Если врач говорил"},
    ],
    "windows": [
        {"code": "morning", "title": "Утром, 8:00–12:00"},
        {"code": "evening", "title": "Вечером, 17:00–21:00"},
    ],
    "texts": {"p1.active.title": "Анализы готовы"},
}
THEME = {"name": "Демо-клиника", "logo_url": None, "accent": "#1D5FD1"}
PATHS = [
    ("get", "/v1/patient/session", None),
    ("post", "/v1/patient/consent", None),
    ("post", "/v1/patient/choice", {"branch_code": "discuss", "goal_id": "x"}),
    ("get", "/v1/patient/doctors", None),
    ("get", "/v1/patient/formats", None),
    ("post", "/v1/patient/requests", {"doctor_id": "x", "format_id": "x",
                                      "window_code": "morning"}),
]
GATED_PATHS = [path for path in PATHS if path[1] != "/v1/patient/session"]
ACTIVE_KEYS = {"state", "clinic", "consent_required", "doctor_step", "branches", "goals",
               "choice", "request", "texts"}


def headers(token: str | None) -> dict:
    return {} if token is None else {"X-Patient-Link": token}


def call(client, method: str, path: str, token: str | None, body=None):
    if method == "get":
        return client.get(path, headers=headers(token))
    return client.post(path, headers=headers(token), json=body)


def error_code(response) -> str:
    return response.json()["detail"]["code"]


# --- фикстуры ------------------------------------------------------------------

@pytest.fixture
def clinic(db_session) -> Clinic:
    clinic = db_session.execute(select(Clinic)).scalar_one()
    clinic.patient_settings = json.dumps(SETTINGS, ensure_ascii=False)
    clinic.theme = json.dumps(THEME, ensure_ascii=False)
    db_session.commit()
    return clinic


@pytest.fixture
def goal(db_session, clinic) -> Goal:
    return db_session.execute(select(Goal)).scalar_one()


@pytest.fixture
def doctor(db_session, clinic, goal) -> Doctor:
    doctor = db_session.execute(select(Doctor)).scalar_one()
    db_session.add(GoalDoctor(goal_id=goal.id, doctor_id=doctor.id, sort_order=1))
    db_session.commit()
    return doctor


@pytest.fixture
def fmt(db_session, clinic) -> Format:
    return db_session.execute(select(Format)).scalar_one()


@pytest.fixture
def make_episode(db_session, clinic):
    counter = iter(range(1000))

    def _make(*, group: str = "main", opted_out: bool = False,
              ordering_doctor: Doctor | None = None, patient_token: str | None = None) -> Episode:
        index = next(counter)
        patient = Patient(clinic_id=clinic.id, patient_token=patient_token or f"pt-b6-{index}",
                          group=group, opted_out=opted_out)
        db_session.add(patient)
        db_session.flush()
        episode = Episode(patient_id=patient.id, group=group,
                          status="control" if group == "control" else "awaiting_doctor",
                          ordering_doctor_id=ordering_doctor.id if ordering_doctor else None,
                          ready_at=datetime(2026, 10, 18, 9, tzinfo=UTC))
        db_session.add(episode)
        db_session.commit()
        return episode

    return _make


def add_link(session: Session, episode: Episode, *, expires_at: datetime | None = None,
             revoked: bool = False) -> str:
    """Ссылка прямо в базе: так можно выдать её и эпизоду контрольной группы."""
    token = new_token()
    now = datetime.now(UTC)
    session.add(PatientLink(episode_id=episode.id, token_hash=hash_token(token),
                            expires_at=expires_at or now + timedelta(days=30),
                            revoked_at=now if revoked else None))
    session.commit()
    return token


@pytest.fixture
def link(db_session, make_episode):
    """Ссылка активного эпизода основной группы."""
    return add_link(db_session, make_episode())


@pytest.fixture
def consented(client, link) -> str:
    assert client.post("/v1/patient/consent", headers=headers(link)).status_code == 200
    return link


@pytest.fixture
def chosen(client, consented, goal, doctor) -> str:
    body = {"branch_code": "discuss", "goal_id": goal.id}
    assert client.post("/v1/patient/choice", headers=headers(consented),
                       json=body).status_code == 200
    return consented


def episode_of(session: Session, token: str) -> Episode:
    session.expire_all()
    link = session.execute(
        select(PatientLink).where(PatientLink.token_hash == hash_token(token))).scalar_one()
    return session.get(Episode, link.episode_id)


def mark_step(session: Session, episode: Episode, doctor: Doctor, code: str, *,
              set_at: datetime | None = None, weeks: int | None = None) -> Step:
    set_at = set_at or datetime.now(UTC)
    step = Step(episode_id=episode.id, kind=code, set_by_doctor_id=doctor.id, set_at=set_at,
                due_date=set_at + timedelta(weeks=weeks) if weeks else None)
    session.add(step)
    session.commit()
    return step


def new_request(client, token: str, doctor: Doctor, fmt: Format, window: str = "morning"):
    return client.post("/v1/patient/requests", headers=headers(token), json={
        "doctor_id": doctor.id, "format_id": fmt.id, "window_code": window})


# --- ссылка ----------------------------------------------------------------------

def test_unknown_revoked_and_control_links_are_the_same_404(client, db_session, make_episode):
    revoked = add_link(db_session, make_episode(), revoked=True)
    control = add_link(db_session, make_episode(group="control"))
    tokens = [None, "", "short", "x" * 129, "bad token with spaces!!", "a.b" * 10,
              new_token(), revoked, control]
    for method, path, body in PATHS:
        bodies = set()
        for token in tokens:
            response = call(client, method, path, token, body)
            assert response.status_code == 404, (path, token)
            bodies.add(response.text)
        assert len(bodies) == 1, path
        assert error_code(response) == "link_not_found"
        assert response.json()["detail"]["message"]


def test_active_session_shape(client, clinic, link, goal):
    response = client.get("/v1/patient/session", headers=headers(link))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == ACTIVE_KEYS
    assert body["state"] == "active"
    assert body["clinic"] == {"name": "Тест-клиника", "phone": SETTINGS["phone"],
                              "privacy_url": SETTINGS["privacy_url"], "theme": THEME}
    assert body["consent_required"] is True
    assert body["doctor_step"] is None
    assert body["branches"] == SETTINGS["branches"]
    assert body["goals"] == [{"id": goal.id, "title": "Цель"}]
    assert body["choice"] is None
    assert body["request"] is None
    assert body["texts"] == SETTINGS["texts"]


def test_session_hides_inactive_goals_and_keeps_order(client, db_session, clinic, link, goal):
    db_session.add_all([
        Goal(clinic_id=clinic.id, title="Первая", sort_order=0),
        Goal(clinic_id=clinic.id, title="Выключена", sort_order=2, is_active=False),
    ])
    db_session.commit()
    goals = client.get("/v1/patient/session", headers=headers(link)).json()["goals"]
    assert [item["title"] for item in goals] == ["Первая", "Цель"]


def test_branch_without_hint_keeps_hint_key(client, db_session, clinic, link):
    settings = {**SETTINGS, "branches": [{"code": "discuss", "title": "Обсудить"}]}
    clinic.patient_settings = json.dumps(settings, ensure_ascii=False)
    db_session.commit()
    body = client.get("/v1/patient/session", headers=headers(link)).json()
    assert body["branches"] == [{"code": "discuss", "title": "Обсудить", "hint": None}]


# --- состояния -------------------------------------------------------------------

@pytest.mark.parametrize(("opted_out", "enabled", "expired", "state"), [
    (True, False, True, "unsubscribed"),
    (True, True, False, "unsubscribed"),
    (False, False, True, "stopped"),
    (False, False, False, "stopped"),
    (False, True, True, "expired"),
])
def test_inactive_states_in_order(client, db_session, clinic, make_episode,
                                  opted_out, enabled, expired, state):
    episode = make_episode(opted_out=opted_out)
    past = datetime.now(UTC) - timedelta(seconds=1)
    token = add_link(db_session, episode, expires_at=past if expired else None)
    clinic.service_enabled = enabled
    db_session.commit()

    response = client.get("/v1/patient/session", headers=headers(token))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"state", "clinic", "texts"}
    assert body["state"] == state
    assert body["texts"] == SETTINGS["texts"]
    for method, path, payload in GATED_PATHS:
        response = call(client, method, path, token, payload)
        assert response.status_code == 409, path
        assert error_code(response) == "not_active"


# --- настройки клиники -----------------------------------------------------------

BROKEN_SETTINGS = [
    None, "", "not json", "[]", "null", "{}",
    *[json.dumps({k: v for k, v in SETTINGS.items() if k != key})
      for key in ("texts", "branches", "windows", "timezone")],
    json.dumps({**SETTINGS, "timezone": "Mars/Base"}),
    json.dumps({**SETTINGS, "timezone": ""}),
    json.dumps({**SETTINGS, "branches": []}),
    json.dumps({**SETTINGS, "windows": []}),
    json.dumps({**SETTINGS, "texts": ["p1"]}),
    json.dumps({**SETTINGS, "branches": [{"code": "discuss"}]}),
    json.dumps({**SETTINGS, "windows": [{"code": "a", "title": "А"}, {"code": "a", "title": "Б"}]}),
]


@pytest.mark.parametrize("raw", BROKEN_SETTINGS)
def test_incomplete_settings_are_503_on_every_path(client, db_session, clinic, link, raw):
    clinic.patient_settings = raw
    db_session.commit()
    for method, path, body in PATHS:
        response = call(client, method, path, link, body)
        assert response.status_code == 503, path
        assert response.json() == {"detail": {
            "code": "not_configured",
            "message": "Страница клиники ещё не настроена. Чтобы записаться к врачу, "
                       "позвоните в клинику."}}


def test_unknown_link_is_404_even_without_settings(client, db_session, clinic):
    clinic.patient_settings = None
    db_session.commit()
    response = client.get("/v1/patient/session", headers=headers(new_token()))
    assert response.status_code == 404


@pytest.mark.parametrize("url", ["http://example-clinic.ru/privacy", "javascript:alert(1)",
                                 "//example-clinic.ru", None])
def test_privacy_url_only_https(client, db_session, clinic, link, url):
    clinic.patient_settings = json.dumps({**SETTINGS, "privacy_url": url})
    db_session.commit()
    body = client.get("/v1/patient/session", headers=headers(link)).json()
    assert body["clinic"]["privacy_url"] is None


def test_theme_ignores_old_keys(client, db_session, clinic, link):
    clinic.theme = '{"logo": "https://example-clinic.ru/l.svg", "title": "Старое", "accent": 5}'
    db_session.commit()
    theme = client.get("/v1/patient/session", headers=headers(link)).json()["clinic"]["theme"]
    assert theme == {"name": None, "logo_url": None, "accent": None}


# --- согласие --------------------------------------------------------------------

def test_consent_required_before_other_actions(client, link, goal, doctor, fmt):
    for method, path, body in GATED_PATHS:
        if path == "/v1/patient/consent":
            continue
        response = call(client, method, path, link, body)
        assert response.status_code == 409, path
        assert error_code(response) == "consent_required"


def test_consent_is_written_once(client, db_session, link):
    for _ in range(2):
        response = client.post("/v1/patient/consent", headers=headers(link))
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    episode = episode_of(db_session, link)
    (consent,) = db_session.execute(select(Consent).where(
        Consent.patient_id == episode.patient_id)).scalars().all()
    assert (consent.kind, consent.granted, consent.source) == ("pd_processing", True, "link")
    (entry,) = db_session.execute(select(AuditEvent).where(
        AuditEvent.action == "patient.consent")).scalars().all()
    assert entry.entity_id == episode.id
    assert entry.role == "patient"
    assert entry.payload is None
    body = client.get("/v1/patient/session", headers=headers(link)).json()
    assert body["consent_required"] is False


def test_consent_of_other_kind_does_not_count(client, db_session, link):
    episode = episode_of(db_session, link)
    db_session.add_all([
        Consent(patient_id=episode.patient_id, kind="marketing", granted=True, source="mis"),
        Consent(patient_id=episode.patient_id, kind="pd_processing", granted=False,
                source="mis"),
    ])
    db_session.commit()
    assert client.get("/v1/patient/session",
                      headers=headers(link)).json()["consent_required"] is True


# --- выбор -----------------------------------------------------------------------

def test_choice_without_doctor_step(client, db_session, consented, goal):
    body = {"branch_code": "retest", "goal_id": goal.id}
    response = client.post("/v1/patient/choice", headers=headers(consented), json=body)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    episode = episode_of(db_session, consented)
    assert (episode.chosen_branch, episode.chosen_goal_id) == ("retest", goal.id)
    session = client.get("/v1/patient/session", headers=headers(consented)).json()
    assert session["choice"] == {"branch_code": "retest", "goal_id": goal.id}


def test_repeated_choice_overwrites(client, db_session, clinic, consented, goal):
    other = Goal(clinic_id=clinic.id, title="Другая", sort_order=5)
    db_session.add(other)
    db_session.commit()
    for branch, goal_id in (("discuss", goal.id), ("retest", other.id)):
        assert client.post("/v1/patient/choice", headers=headers(consented), json={
            "branch_code": branch, "goal_id": goal_id}).status_code == 200
    episode = episode_of(db_session, consented)
    assert (episode.chosen_branch, episode.chosen_goal_id) == ("retest", other.id)


def test_choice_validation_without_doctor_step(client, db_session, clinic, consented, goal):
    inactive = Goal(clinic_id=clinic.id, title="Выключена", is_active=False)
    foreign_clinic = Clinic(name="Чужая", service_enabled=True)
    db_session.add_all([inactive, foreign_clinic])
    db_session.flush()
    foreign = Goal(clinic_id=foreign_clinic.id, title="Чужая цель")
    db_session.add(foreign)
    db_session.commit()
    for body in (
        {"goal_id": goal.id},
        {"branch_code": None, "goal_id": goal.id},
        {"branch_code": "followup", "goal_id": goal.id},
        {"branch_code": "discuss", "goal_id": inactive.id},
        {"branch_code": "discuss", "goal_id": foreign.id},
        {"branch_code": "discuss", "goal_id": "missing"},
        {"branch_code": "discuss"},
        {"branch_code": "discuss", "goal_id": goal.id, "comment": "x"},
        {"branch_code": 1, "goal_id": goal.id},
        [],
    ):
        response = client.post("/v1/patient/choice", headers=headers(consented), json=body)
        assert response.status_code == 422, body
        assert error_code(response) == "invalid_input"
    episode = episode_of(db_session, consented)
    assert episode.chosen_goal_id is None


def test_choice_with_doctor_step_requires_null_branch(client, db_session, consented, goal,
                                                      doctor):
    mark_step(db_session, episode_of(db_session, consented), doctor, "discuss")
    response = client.post("/v1/patient/choice", headers=headers(consented),
                           json={"branch_code": "discuss", "goal_id": goal.id})
    assert response.status_code == 422
    for body in ({"branch_code": None, "goal_id": goal.id}, {"goal_id": goal.id}):
        assert client.post("/v1/patient/choice", headers=headers(consented),
                           json=body).status_code == 200
    episode = episode_of(db_session, consented)
    assert (episode.chosen_branch, episode.chosen_goal_id) == (None, goal.id)


@pytest.mark.parametrize("path", ["/v1/patient/doctors", "/v1/patient/formats",
                                  "/v1/patient/requests"])
def test_choice_required_before_doctors_formats_requests(client, consented, doctor, fmt, path):
    if path.endswith("requests"):
        response = new_request(client, consented, doctor, fmt)
    else:
        response = client.get(path, headers=headers(consented))
    assert response.status_code == 409
    assert error_code(response) == "choice_required"


# --- шаг врача -------------------------------------------------------------------

def test_doctor_step_for_non_retest(client, db_session, link, doctor):
    mark_step(db_session, episode_of(db_session, link), doctor, "followup")
    step = client.get("/v1/patient/session", headers=headers(link)).json()["doctor_step"]
    assert step == {"code": "followup", "retest_weeks": None, "due_date": None,
                    "retest_state": None, "doctor_name": "Тестовый Врач"}


@pytest.mark.parametrize(("shift", "state"), [
    (timedelta(days=3), "before"), (timedelta(0), "today"), (timedelta(days=-3), "overdue"),
])
def test_retest_state_by_today(client, db_session, link, doctor, shift, state):
    due = datetime.now(UTC) + shift
    mark_step(db_session, episode_of(db_session, link), doctor, "retest",
              set_at=due - timedelta(weeks=4), weeks=4)
    step = client.get("/v1/patient/session", headers=headers(link)).json()["doctor_step"]
    assert step["code"] == "retest"
    assert step["retest_weeks"] == 4
    assert step["retest_state"] == state
    assert step["doctor_name"] == "Тестовый Врач"


def test_retest_dates_are_in_clinic_timezone(db_session, clinic, make_episode, doctor):
    episode = make_episode()
    token = add_link(db_session, episode, expires_at=datetime(2027, 1, 1, tzinfo=UTC))
    db_session.add(Consent(patient_id=episode.patient_id, kind="pd_processing", granted=True))
    due = datetime(2026, 11, 16, 21, 30, tzinfo=UTC)  # 17.11 00:30 по Москве
    mark_step(db_session, episode, doctor, "retest", set_at=due - timedelta(weeks=2), weeks=2)

    def step_at(now: datetime) -> dict:
        info = PatientService(db_session).session_info(token, now=now)
        assert info.doctor_step is not None
        return info.doctor_step.model_dump(mode="json")

    evening = step_at(datetime(2026, 11, 16, 20, 0, tzinfo=UTC))  # 16.11 23:00 по Москве
    assert evening["due_date"] == "2026-11-17"
    assert evening["retest_weeks"] == 2
    assert evening["retest_state"] == "before"
    assert step_at(datetime(2026, 11, 16, 21, 0, tzinfo=UTC))["retest_state"] == "today"
    assert step_at(datetime(2026, 11, 17, 21, 0, tzinfo=UTC))["retest_state"] == "overdue"


def test_latest_doctor_step_wins_and_unmarked_steps_are_ignored(client, db_session, link,
                                                                doctor):
    episode = episode_of(db_session, link)
    now = datetime.now(UTC)
    mark_step(db_session, episode, doctor, "discuss", set_at=now - timedelta(hours=2))
    mark_step(db_session, episode, doctor, "followup", set_at=now - timedelta(hours=1))
    db_session.add(Step(episode_id=episode.id, kind="retest", set_at=now))
    db_session.commit()
    step = client.get("/v1/patient/session", headers=headers(link)).json()["doctor_step"]
    assert step["code"] == "followup"


# --- форматы ---------------------------------------------------------------------

def test_formats_and_windows(client, db_session, clinic, chosen, fmt):
    db_session.add_all([
        Format(clinic_id=clinic.id, title="Быстрый ответ", price_kopecks=50000,
               payment_url="https://example-clinic.ru/pay/quick"),
        Format(clinic_id=clinic.id, title="Без https", price_kopecks=1,
               payment_url="http://example-clinic.ru/pay"),
        Format(clinic_id=clinic.id, title="Выключен", is_active=False),
    ])
    db_session.commit()
    response = client.get("/v1/patient/formats", headers=headers(chosen))
    assert response.status_code == 200
    body = response.json()
    assert body["windows"] == SETTINGS["windows"]
    by_title = {item["title"]: item for item in body["formats"]}
    assert set(by_title) == {"Приём", "Быстрый ответ", "Без https"}
    assert by_title["Приём"] == {"id": fmt.id, "title": "Приём", "price_kopecks": 100000,
                                 "currency": "RUB", "has_payment": False}
    assert by_title["Быстрый ответ"]["has_payment"] is True
    assert by_title["Без https"]["has_payment"] is False
    assert "example-clinic.ru/pay" not in response.text


# --- заявка ----------------------------------------------------------------------

def test_create_request(client, db_session, chosen, goal, doctor, fmt):
    response = new_request(client, chosen, doctor, fmt, "evening")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"request_id", "status", "payment_url"}
    assert body["status"] == "accepted"
    assert body["payment_url"] is None

    db_session.expire_all()
    request = db_session.get(Request, body["request_id"])
    episode = episode_of(db_session, chosen)
    assert (request.episode_id, request.patient_id, request.doctor_id, request.format_id,
            request.goal_id, request.window, request.status) == (
        episode.id, episode.patient_id, doctor.id, fmt.id, goal.id, "evening", "new")

    (job,) = db_session.execute(select(Outbox).where(Outbox.topic == "crm")).scalars().all()
    assert json.loads(job.payload) == {"request_id": request.id}
    assert job.status == "pending"
    (entry,) = db_session.execute(select(AuditEvent).where(
        AuditEvent.action == "patient.request_created")).scalars().all()
    assert json.loads(entry.payload) == {"request_id": request.id}
    assert entry.entity_id == episode.id

    session = client.get("/v1/patient/session", headers=headers(chosen)).json()
    assert session["request"]["id"] == request.id
    assert session["request"]["status"] == "accepted"
    assert session["request"]["doctor_name"] == "Тестовый Врач"
    assert session["request"]["format_title"] == "Приём"
    assert session["request"]["window_title"] == "Вечером, 17:00–21:00"
    assert datetime.fromisoformat(session["request"]["created_at"]).tzinfo is not None


@pytest.mark.parametrize(("url", "expected"), [
    ("https://example-clinic.ru/pay/quick", "https://example-clinic.ru/pay/quick"),
    ("http://example-clinic.ru/pay/quick", None),
    ("javascript:alert(1)", None),
])
def test_request_payment_url_only_https(client, db_session, chosen, doctor, fmt, url, expected):
    fmt.payment_url = url
    db_session.commit()
    response = new_request(client, chosen, doctor, fmt)
    assert response.status_code == 201
    assert response.json()["payment_url"] == expected


def test_one_open_request_per_episode(client, db_session, chosen, doctor, fmt):
    first = new_request(client, chosen, doctor, fmt)
    assert first.status_code == 201
    for status in ("new", "sent", "in_progress"):
        db_session.get(Request, first.json()["request_id"]).status = status
        db_session.commit()
        second = new_request(client, chosen, doctor, fmt)
        assert second.status_code == 409
        assert error_code(second) == "request_exists"
    db_session.get(Request, first.json()["request_id"]).status = "cancelled"
    db_session.commit()
    assert new_request(client, chosen, doctor, fmt).status_code == 201
    db_session.expire_all()
    assert len(db_session.execute(select(Request)).scalars().all()) == 2
    assert len(db_session.execute(select(Outbox)).scalars().all()) == 2


def test_request_validation(client, db_session, clinic, chosen, doctor, fmt):
    stranger = Doctor(clinic_id=clinic.id, external_id="doc-x", full_name="Не из цели")
    inactive = Format(clinic_id=clinic.id, title="Выключен", is_active=False)
    db_session.add_all([stranger, inactive])
    db_session.commit()
    for body in (
        {"doctor_id": stranger.id, "format_id": fmt.id, "window_code": "morning"},
        {"doctor_id": doctor.id, "format_id": inactive.id, "window_code": "morning"},
        {"doctor_id": doctor.id, "format_id": "missing", "window_code": "morning"},
        {"doctor_id": doctor.id, "format_id": fmt.id, "window_code": "night"},
        {"doctor_id": doctor.id, "format_id": fmt.id},
        {"doctor_id": doctor.id, "format_id": fmt.id, "window_code": "morning", "phone": "1"},
        {"doctor_id": doctor.id, "format_id": fmt.id, "window_code": 5},
        [],
    ):
        response = client.post("/v1/patient/requests", headers=headers(chosen), json=body)
        assert response.status_code == 422, body
        assert error_code(response) == "invalid_input"
    db_session.expire_all()
    assert db_session.execute(select(Request)).scalars().all() == []
    assert db_session.execute(select(Outbox)).scalars().all() == []


@pytest.mark.parametrize(("path", "body"), [
    ("/v1/patient/choice", {"branch_code": "+79990000000", "goal_id": "+79990000000x"}),
    ("/v1/patient/choice", {"goal_id": "g", "phone": "+79990000000"}),
    ("/v1/patient/requests", {"doctor_id": "+79990000000", "format_id": "f",
                              "window_code": "morning", "note": "+79990000000"}),
])
def test_422_does_not_echo_body(client, chosen, path, body):
    response = client.post(path, headers=headers(chosen), json=body)
    assert response.status_code == 422
    assert "79990000000" not in response.text
    assert "\"input\"" not in response.text


def test_malformed_json_is_anonymous_422(client, chosen):
    response = client.post("/v1/patient/requests", content=b'{"doctor_id": "+79990000000"',
                           headers={**headers(chosen), "Content-Type": "application/json"})
    assert response.status_code == 422
    assert error_code(response) == "invalid_input"
    assert "79990000000" not in response.text


@pytest.mark.parametrize(("status", "shown"), [
    ("new", "accepted"), ("sent", "accepted"), ("in_progress", "in_progress"),
    ("booked", "booked"), ("cancelled", "cancelled"),
])
def test_request_status_for_patient(client, db_session, chosen, doctor, fmt, status, shown):
    request_id = new_request(client, chosen, doctor, fmt).json()["request_id"]
    db_session.get(Request, request_id).status = status
    db_session.commit()
    session = client.get("/v1/patient/session", headers=headers(chosen)).json()
    assert session["request"]["status"] == shown


def test_session_prefers_open_request_over_newer_finished(client, db_session, chosen, doctor,
                                                          fmt):
    episode = episode_of(db_session, chosen)
    now = datetime.now(UTC)
    open_request = Request(episode_id=episode.id, patient_id=episode.patient_id,
                           doctor_id=doctor.id, format_id=fmt.id, window="morning",
                           status="sent", created_at=now - timedelta(hours=2))
    finished = Request(episode_id=episode.id, patient_id=episode.patient_id,
                       doctor_id=doctor.id, format_id=fmt.id, window="gone",
                       status="booked", created_at=now - timedelta(hours=1))
    db_session.add_all([open_request, finished])
    db_session.commit()
    request = client.get("/v1/patient/session", headers=headers(chosen)).json()["request"]
    assert request["id"] == open_request.id
    open_request.status = "cancelled"
    db_session.commit()
    request = client.get("/v1/patient/session", headers=headers(chosen)).json()["request"]
    assert request["id"] == finished.id
    assert request["status"] == "booked"
    assert request["window_title"] is None


# --- ПДн нигде нет ------------------------------------------------------------------

def test_no_personal_data_in_responses_audit_outbox_and_logs(
    client, sign_headers, db_session, clinic, goal, doctor, fmt, caplog,
):
    caplog.set_level(logging.DEBUG)
    patient_token = next(f"pt-pd-{i}" for i in range(1000)
                         if assign_group(f"pt-pd-{i}") == Group.MAIN)
    event = {**EVENT, "patient_token": patient_token, "ordering_doctor_id": "doc-1"}
    raw = json.dumps(event).encode()
    episode_id = client.post("/v1/mis/results-ready", content=raw,
                             headers=sign_headers(raw)).json()["episode_id"]
    token = issue_link(db_session, episode_id, datetime.now(UTC))

    texts = [
        client.get("/v1/patient/session", headers=headers(token)).text,
        client.post("/v1/patient/consent", headers=headers(token)).text,
        client.post("/v1/patient/choice", headers=headers(token),
                    json={"branch_code": "discuss", "goal_id": goal.id}).text,
        client.get("/v1/patient/doctors", headers=headers(token)).text,
        client.get("/v1/patient/formats", headers=headers(token)).text,
        new_request(client, token, doctor, fmt).text,
        client.get("/v1/patient/session", headers=headers(token)).text,
    ]
    db_session.expire_all()
    patient_audit = db_session.execute(select(AuditEvent).where(
        AuditEvent.action.like("patient.%"))).scalars().all()
    assert {entry.action for entry in patient_audit} == {"patient.consent",
                                                         "patient.request_created"}
    texts += [f"{entry.actor_id} {entry.entity_id} {entry.payload}" for entry in patient_audit]
    texts += [job.payload for job in db_session.execute(select(Outbox)).scalars()]
    texts.append(caplog.text)
    joined = "\n".join(texts)
    assert '"request_id"' in joined  # заявка действительно создана
    for private in (token, hash_token(token), patient_token, "9001234567", EVENT["phone"]):
        assert private not in joined


# --- гонка двух заявок (PostgreSQL) ----------------------------------------------------

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
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return results


@needs_postgres
def test_two_simultaneous_requests_give_one_request(db_session, chosen, doctor, fmt, parallel):
    with TestClient(fastapi_app) as c1, TestClient(fastapi_app) as c2:
        codes = run_together(lambda: new_request(c1, chosen, doctor, fmt).status_code,
                             lambda: new_request(c2, chosen, doctor, fmt).status_code)
    assert sorted(codes) == [201, 409]
    db_session.expire_all()
    assert len(db_session.execute(select(Request)).scalars().all()) == 1
    assert len(db_session.execute(select(Outbox).where(
        Outbox.topic == "crm")).scalars().all()) == 1


# --- демо-данные ---------------------------------------------------------------------

def test_seed_demo_configures_patient_page(empty_engine, monkeypatch):
    from contextlib import contextmanager

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
        assert json.loads(clinic.theme) == {"name": "Клиника", "logo_url": None,
                                            "accent": "#2F6FED"}
        settings = json.loads(clinic.patient_settings)
        assert [item["code"] for item in settings["branches"]] == ["discuss", "retest",
                                                                   "followup"]
        assert [item["code"] for item in settings["windows"]] == ["morning", "day", "evening",
                                                                  "any"]
        prefixes = {key.split(".")[0] for key in settings["texts"]}
        assert {"p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "err"} == prefixes
        goals = session.execute(select(Goal).order_by(Goal.sort_order)).scalars().all()
        assert [goal.title for goal in goals] == [
            "Обсудить анализы с врачом", "Пересдать анализы",
            "Повторный приём у своего врача", "Другой вопрос к врачу"]
        formats = {item.title: item for item in session.execute(select(Format)).scalars()}
        assert set(formats) == {"Приём в клинике", "Онлайн-консультация", "Быстрый ответ врача"}
        assert formats["Быстрый ответ врача"].payment_url.startswith("https://example-clinic.ru/")
        pairs = session.execute(select(GoalDoctor)).scalars().all()
        assert len(pairs) == 4 * 3
        first = {pair.goal_id: pair for pair in pairs if pair.sort_order == 1}
        therapist = session.get(Doctor, next(iter(first.values())).doctor_id)
        assert therapist.specialty == "Терапевт"
        texts = " ".join(settings["texts"].values()).lower()
        for word in ("расшифровк", "риск", "срочно", "отклонени", "диагноз"):
            assert word not in texts


@pytest.mark.parametrize("path", ["/v1/patient/choice", "/v1/patient/requests"])
def test_unknown_link_is_404_before_body_validation(client, db_session, make_episode, path):
    control = add_link(db_session, make_episode(group="control"))
    for token in (None, new_token(), control):
        response = client.post(path, headers=headers(token), json={"phone": "+79990000000"})
        assert response.status_code == 404
        assert error_code(response) == "link_not_found"
