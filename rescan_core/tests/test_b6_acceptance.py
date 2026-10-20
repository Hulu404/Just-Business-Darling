"""Приёмочные тесты B6 (API пациента) по разделу «Контракты» задания 19.

Чёрный ящик: события приходят через HTTP с подписью, врач отмечает шаг через
`/v1/doctor/...`, пациент работает через `/v1/patient/...` с заголовком `X-Patient-Link`.
Подготовка — через ORM (не сырым UPDATE: см. отчёт 18). Ссылку выдаёт контрактная
функция `issue_link(session, episode_id, now)` из `app.services.patient_service`.

Новые таблицы (`patient_links`, `goal_doctors`) ищем по имени таблицы, а не по имени
класса: контракт называет только таблицы. Новые колонки проверяем перед записью, чтобы
до появления моделей B6 тест падал понятным сообщением.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.base import Base
from app.db.models import (
    AuditEvent,
    Clinic,
    Consent,
    Doctor,
    Episode,
    Format,
    Goal,
    Outbox,
    Request,
    Step,
    Visit,
)
from app.db.session import get_session
from app.main import app as fastapi_app
from app.services.group_service import Group, assign_group

DOCTOR = {"X-Staff-Token": "dev-doctor-token"}  # actor_id dev-doctor
PHONE = "+7 (900) 000-00-61"
PHONE_DIGITS = ("9000000061", "79000000061", "000-00-61")
CLINIC_NAME = "Тест-клиника"  # из conftest
THEME = {"name": CLINIC_NAME, "logo_url": None, "accent": "#1D5FD1"}
STEP_OPTIONS = [
    {"code": "discuss", "title": "Обсудить на приёме"},
    {"code": "retest", "title": "Пересдать через несколько недель", "weeks": [2, 4, 8, 12]},
    {"code": "followup", "title": "Контроль у меня"},
]
BRANCHES = [
    {"code": "discuss", "title": "Обсудить с врачом", "hint": "Синтетическая подсказка"},
    {"code": "checkup", "title": "Плановый осмотр", "hint": "Синтетическая подсказка 2"},
]
WINDOWS = [
    {"code": "morning", "title": "Утром, 8:00–12:00"},
    {"code": "evening", "title": "Вечером, 17:00–21:00"},
]
TEXTS = {"p1.active.title": "Синтетический заголовок", "p4.title": "Синтетические врачи"}
SETTINGS = {
    "phone": "+7 000 000-00-00",
    "privacy_url": "https://example-clinic.ru/privacy",
    "timezone": "Europe/Moscow",
    "branches": BRANCHES,
    "windows": WINDOWS,
    "texts": TEXTS,
}
MSK = timedelta(hours=3)  # Europe/Moscow без перехода на летнее время с 2014 года
PAY_HTTPS = "https://example-clinic.ru/pay/quick"
PAY_HTTP = "http://example-clinic.ru/pay/online"
SESSION_KEYS = {"state", "clinic", "consent_required", "doctor_step", "branches", "goals",
                "choice", "request", "texts"}
ECHO = "qa-echo-marker-6061"


# ---------- поиск новых таблиц и колонок B6 ----------

def mapped(table: str):
    """Класс модели по имени таблицы: контракт называет таблицы, а не классы."""
    for mapper in Base.registry.mappers:
        if getattr(mapper.local_table, "name", None) == table:
            return mapper.class_
    pytest.fail(f"нет модели таблицы {table}: ждём миграцию и модели B6")


def need_column(model, name: str) -> None:
    if name not in model.__table__.columns:
        pytest.fail(f"нет колонки {model.__tablename__}.{name}: ждём миграцию и модели B6")


def put(session, obj, **values) -> None:
    """Записать колонки через ORM (настройки и данные — не сырым UPDATE)."""
    for name, value in values.items():
        need_column(type(obj), name)
        setattr(obj, name, value)
    session.commit()


def fresh(session, model, key):
    session.expire_all()
    return session.get(model, key)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def no_secrets(blob: str, *extra: str) -> None:
    for item in PHONE_DIGITS + tuple(x for x in extra if x):
        assert item not in blob


# ---------- подготовка ----------

@pytest.fixture
def clinic(db_session, monkeypatch):
    """Клиника из conftest: тема, шаги врача, настройки пациента, врач-сотрудник."""
    clinic = db_session.execute(select(Clinic)).scalar_one()
    # Вторую клинику тесты добавляют сами: интеграционная клиника задаётся явно.
    monkeypatch.setattr(get_settings(), "mis_clinic_id", clinic.id)
    clinic.theme = json.dumps(THEME, ensure_ascii=False)
    clinic.step_options = json.dumps(STEP_OPTIONS, ensure_ascii=False)
    db_session.add(Doctor(clinic_id=clinic.id, external_id="dev-doctor",
                          full_name="Синтетический Врач", specialty="Терапевт"))
    db_session.commit()
    put(db_session, clinic, patient_settings=json.dumps(SETTINGS, ensure_ascii=False))
    return clinic


@pytest.fixture
def issue(db_session):
    """Контрактная выдача ссылки. Импорт здесь: до B6 падает этот тест, а не сбор."""
    from app.services.patient_service import issue_link

    def _issue(episode_id: str, now: datetime | None = None) -> str:
        token = issue_link(db_session, episode_id, now or datetime.now(UTC))
        db_session.commit()
        return token

    return _issue


def token_in(group: Group, n: int = 0) -> str:
    found = (f"b6-pt-{i}" for i in range(5000) if assign_group(f"b6-pt-{i}") == group)
    for _ in range(n):
        next(found)
    return next(found)


def ingest(client, sign_headers, n: int = 0, group: Group = Group.MAIN,
           doctor: str = "dev-doctor") -> tuple[str, str]:
    """Эпизод через `/v1/mis/results-ready`; вернуть (episode_id, patient_token)."""
    token = token_in(group, n)
    body = json.dumps({
        "event_id": f"b6-evt-{group.value}-{n}-{doctor}", "branch_id": "br-1",
        "patient_token": token, "phone": PHONE, "ordering_doctor_id": doctor,
        "ready_at": "2026-10-14T09:00:00+03:00", "marketing_consent": True,
    }).encode()
    response = client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["group"] == group.value
    return result["episode_id"], token


def mark(client, episode_id: str, code: str = "discuss", weeks: int | None = None) -> None:
    body: dict = {"code": code}
    if weeks is not None:
        body["retest_weeks"] = weeks
    response = client.post(f"/v1/doctor/episodes/{episode_id}/step",
                           content=json.dumps(body).encode(),
                           headers={**DOCTOR, "Content-Type": "application/json"})
    assert response.status_code == 201, response.text


def link_headers(link: str | None) -> dict:
    return {} if link is None else {"X-Patient-Link": link}


def get(client, path: str, link: str | None):
    return client.get("/v1/patient" + path, headers=link_headers(link))


def post(client, path: str, link: str | None, body=None):
    if body is None:
        return client.post("/v1/patient" + path, headers=link_headers(link))
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    return client.post("/v1/patient" + path, content=payload,
                       headers={**link_headers(link), "Content-Type": "application/json"})


def expect_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert re.search(r"[А-Яа-яЁё]", detail["message"]), "message — по-русски"
    return detail


def link_row(session, episode_id: str):
    links = mapped("patient_links")
    session.expire_all()
    rows = session.execute(select(links).where(links.episode_id == episode_id)).scalars().all()
    assert len(rows) == 1
    return rows[0]


class Patient6:
    """Пациент сценария: эпизод, patient_token и ссылка."""

    def __init__(self, episode_id: str, patient_token: str, link: str) -> None:
        self.episode_id = episode_id
        self.patient_token = patient_token
        self.link = link


@pytest.fixture
def catalog(db_session, clinic):
    """Цели, врачи, связи цель→врач и форматы. Порядок вставки — обратный ожидаемому."""
    goal_doctors = mapped("goal_doctors")
    goal_main = Goal(clinic_id=clinic.id, title="Синтетическая цель 1", sort_order=2)
    goal_other = Goal(clinic_id=clinic.id, title="Синтетическая цель 2", sort_order=3)
    goal_off = Goal(clinic_id=clinic.id, title="Выключенная цель", sort_order=0, is_active=False)
    db_session.add_all([goal_off, goal_other, goal_main])
    doctors = {
        "visited_recent": Doctor(clinic_id=clinic.id, external_id="qa-v", full_name="Яковлев Синт",
                                 specialty="Кардиолог"),
        "visited_old": Doctor(clinic_id=clinic.id, external_id="qa-s", full_name="Борисов Синт",
                              specialty="Эндокринолог"),
        "therapist": Doctor(clinic_id=clinic.id, external_id="qa-t", full_name="Алексеев Синт",
                            specialty="Терапевт"),
        "inactive": Doctor(clinic_id=clinic.id, external_id="qa-i", full_name="Неактивный Синт",
                           is_active=False),
        "not_in_goal": Doctor(clinic_id=clinic.id, external_id="qa-x",
                              full_name="Посторонний Синт"),
        "other_goal": Doctor(clinic_id=clinic.id, external_id="qa-w", full_name="Другой Синт"),
    }
    db_session.add_all(list(doctors.values()))
    db_session.flush()
    db_session.add_all([
        goal_doctors(goal_id=goal_main.id, doctor_id=doctors["inactive"].id, sort_order=4),
        goal_doctors(goal_id=goal_main.id, doctor_id=doctors["visited_recent"].id, sort_order=3),
        goal_doctors(goal_id=goal_main.id, doctor_id=doctors["visited_old"].id, sort_order=2),
        goal_doctors(goal_id=goal_main.id, doctor_id=doctors["therapist"].id, sort_order=1),
        goal_doctors(goal_id=goal_other.id, doctor_id=doctors["other_goal"].id, sort_order=1),
    ])
    plain = db_session.execute(select(Format).where(Format.clinic_id == clinic.id)).scalar_one()
    formats = {
        "plain": plain,
        "https": Format(clinic_id=clinic.id, title="Быстрый ответ врача", price_kopecks=50000,
                        payment_url=PAY_HTTPS),
        "http": Format(clinic_id=clinic.id, title="Онлайн-консультация", price_kopecks=150000,
                       payment_url=PAY_HTTP),
        "inactive": Format(clinic_id=clinic.id, title="Снятый формат", price_kopecks=1,
                           is_active=False),
    }
    db_session.add_all([formats["https"], formats["http"], formats["inactive"]])
    db_session.commit()
    return {"goal": goal_main, "goal_other": goal_other, "goal_off": goal_off,
            "doctors": doctors, "formats": formats}


def add_visits(session, clinic, patient_token: str, catalog) -> None:
    now = datetime.now(UTC)
    d = catalog["doctors"]
    session.add_all([
        Visit(clinic_id=clinic.id, patient_token=patient_token, doctor_external_id=external_id,
              visit_date=now - timedelta(days=days))
        for external_id, days in ((d["visited_old"].external_id, 100),
                                  (d["visited_recent"].external_id, 10),
                                  (d["not_in_goal"].external_id, 1))
    ])
    session.commit()


@pytest.fixture
def marked(client, sign_headers, clinic, issue):
    """Эпизод основной группы с шагом врача discuss и ссылкой, без согласия и выбора."""
    episode_id, token = ingest(client, sign_headers)
    mark(client, episode_id, "discuss")
    return Patient6(episode_id, token, issue(episode_id))


@pytest.fixture
def ready(client, db_session, clinic, catalog, marked):
    """Согласие дано, цель выбрана, есть визиты — можно смотреть врачей и оставлять заявку."""
    add_visits(db_session, clinic, marked.patient_token, catalog)
    assert post(client, "/consent", marked.link).status_code == 200
    response = post(client, "/choice", marked.link,
                    {"branch_code": None, "goal_id": catalog["goal"].id})
    assert response.status_code == 200, response.text
    return marked


def request_body(catalog, doctor="therapist", fmt="plain", window="morning") -> dict:
    return {"doctor_id": catalog["doctors"][doctor].id,
            "format_id": catalog["formats"][fmt].id, "window_code": window}


# ---------- ссылка: выдача и хранение ----------

def test_issue_link_stores_only_hmac_and_ttl(db_session, client, sign_headers, clinic, issue):
    episode_id, _ = ingest(client, sign_headers)
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    token = issue(episode_id, now)
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token)
    assert len(token) >= 43  # secrets.token_urlsafe(32)
    row = link_row(db_session, episode_id)
    secret = get_settings().patient_link_secret
    assert row.token_hash == hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    assert row.revoked_at is None
    assert get_settings().patient_link_ttl_days == 30
    assert aware(row.expires_at) == now + timedelta(days=30)
    for column in row.__table__.columns:
        assert token not in str(getattr(row, column.key))


def test_link_secret_and_ttl_settings():
    from pydantic import ValidationError

    from app.config import Settings

    assert get_settings().patient_link_secret.startswith("dev-")
    for ttl in (0, 91):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, patient_link_ttl_days=ttl)
    assert Settings(_env_file=None, patient_link_ttl_days=90).patient_link_ttl_days == 90


# ---------- 404 link_not_found: одинаковый ответ ----------

PATIENT_CALLS = [
    ("GET", "/session", None), ("POST", "/consent", None),
    ("POST", "/choice", {"branch_code": None, "goal_id": "x"}),
    ("GET", "/doctors", None), ("GET", "/formats", None),
    ("POST", "/requests", {"doctor_id": "x", "format_id": "x", "window_code": "morning"}),
]


def call(client, method: str, path: str, link: str | None, body=None):
    return get(client, path, link) if method == "GET" else post(client, path, link, body)


@pytest.mark.parametrize("method,path,body", PATIENT_CALLS)
def test_missing_or_malformed_or_unknown_link_is_same_404(client, clinic, method, path, body):
    links = [None, "", "short", "a" * 15, "a" * 129, "bad token with spaces 123",
             "abc$%^&*()abc$%^&*()", secrets.token_urlsafe(32)]
    answers = []
    for link in links:
        response = call(client, method, path, link, body)
        expect_error(response, 404, "link_not_found")
        answers.append(response.json())
    assert all(answer == answers[0] for answer in answers)


def test_revoked_and_control_links_look_like_unknown(client, db_session, sign_headers, clinic,
                                                     issue, marked):
    unknown = get(client, "/session", secrets.token_urlsafe(32))
    expect_error(unknown, 404, "link_not_found")
    assert get(client, "/session", marked.link).status_code == 200
    put(db_session, link_row(db_session, marked.episode_id), revoked_at=datetime.now(UTC))
    revoked = get(client, "/session", marked.link)
    assert (revoked.status_code, revoked.json()) == (404, unknown.json())

    control_id, _ = ingest(client, sign_headers, group=Group.CONTROL)
    try:
        control_link = issue(control_id)
    except Exception:
        # отказ выдать ссылку контрольной группе тоже соответствует контракту
        db_session.rollback()
        return
    for method, path, body in PATIENT_CALLS:
        response = call(client, method, path, control_link, body)
        assert (response.status_code, response.json()) == (404, unknown.json()), path


# ---------- GET /session ----------

def test_active_session_shape(client, db_session, clinic, catalog, marked):
    response = get(client, "/session", marked.link)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == SESSION_KEYS
    assert body["state"] == "active"
    assert body["clinic"] == {"name": CLINIC_NAME, "phone": SETTINGS["phone"],
                              "privacy_url": SETTINGS["privacy_url"], "theme": THEME}
    assert body["consent_required"] is True
    assert body["doctor_step"] == {"code": "discuss", "retest_weeks": None, "due_date": None,
                                   "retest_state": None, "doctor_name": "Синтетический Врач"}
    assert body["branches"] == BRANCHES
    conftest_goal = db_session.execute(select(Goal).where(Goal.title == "Цель")).scalar_one()
    assert body["goals"] == [{"id": g.id, "title": g.title}
                             for g in (conftest_goal, catalog["goal"], catalog["goal_other"])]
    assert body["choice"] is None
    assert body["request"] is None
    assert body["texts"] == TEXTS


def test_session_without_doctor_step(client, sign_headers, clinic, issue):
    episode_id, _ = ingest(client, sign_headers)
    body = get(client, "/session", issue(episode_id)).json()
    assert body["doctor_step"] is None
    assert body["branches"] == BRANCHES


def test_retest_step_due_date_in_clinic_timezone(client, db_session, sign_headers, clinic, issue):
    episode_id, _ = ingest(client, sign_headers)
    mark(client, episode_id, "retest", 4)
    link = issue(episode_id)
    step = db_session.execute(select(Step).where(Step.episode_id == episode_id)).scalar_one()
    expected = (aware(step.due_date) + MSK).date().isoformat()
    body = get(client, "/session", link).json()
    assert body["doctor_step"] == {"code": "retest", "retest_weeks": 4, "due_date": expected,
                                   "retest_state": "before", "doctor_name": "Синтетический Врач"}


@pytest.mark.parametrize("shift,state", [(timedelta(0), "today"),
                                         (-timedelta(days=2), "overdue"),
                                         (timedelta(days=2), "before")])
def test_retest_state_by_clinic_today(client, db_session, sign_headers, clinic, issue, shift,
                                      state):
    episode_id, _ = ingest(client, sign_headers)
    mark(client, episode_id, "retest", 2)
    link = issue(episode_id)
    step = db_session.execute(select(Step).where(Step.episode_id == episode_id)).scalar_one()
    due = datetime.now(UTC) + shift
    put(db_session, step, due_date=due)
    step_view = get(client, "/session", link).json()["doctor_step"]
    assert step_view["retest_state"] == state
    assert step_view["due_date"] == (due + MSK).date().isoformat()


def test_http_privacy_url_is_null(client, db_session, clinic, marked):
    put(db_session, clinic, patient_settings=json.dumps(
        {**SETTINGS, "privacy_url": "http://example-clinic.ru/privacy"}, ensure_ascii=False))
    assert get(client, "/session", marked.link).json()["clinic"]["privacy_url"] is None


def stop(session, clinic):
    put(session, clinic, service_enabled=False)


def expire(session, episode_id):
    put(session, link_row(session, episode_id), expires_at=datetime.now(UTC) - timedelta(minutes=1))


def unsubscribe(session, episode_id):
    patient = fresh(session, Episode, episode_id).patient
    put(session, patient, opted_out=True)


@pytest.mark.parametrize("changes,state", [
    (("expire",), "expired"), (("stop",), "stopped"), (("unsubscribe",), "unsubscribed"),
    (("expire", "stop"), "stopped"), (("expire", "unsubscribe"), "unsubscribed"),
    (("expire", "stop", "unsubscribe"), "unsubscribed"),
])
def test_inactive_states_in_contract_order(client, db_session, clinic, marked, changes, state):
    actions = {"expire": lambda: expire(db_session, marked.episode_id),
               "stop": lambda: stop(db_session, clinic),
               "unsubscribe": lambda: unsubscribe(db_session, marked.episode_id)}
    for change in changes:
        actions[change]()
    response = get(client, "/session", marked.link)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"state", "clinic", "texts"}
    assert body["state"] == state
    assert body["clinic"]["phone"] == SETTINGS["phone"]


@pytest.mark.parametrize("broken", [
    None, "", "не json", "[]",
    *[json.dumps({k: v for k, v in SETTINGS.items() if k != key}, ensure_ascii=False)
      for key in ("texts", "branches", "windows", "timezone")],
], ids=["null", "empty", "not-json", "list", "no-texts", "no-branches", "no-windows",
        "no-timezone"])
def test_incomplete_patient_settings_is_503(client, db_session, clinic, ready, broken):
    put(db_session, clinic, patient_settings=broken)
    for path in ("/session", "/doctors", "/formats"):
        detail = expect_error(get(client, path, ready.link), 503, "not_configured")
        assert "Страница клиники ещё не настроена" in detail["message"]


# ---------- POST /consent ----------

def test_consent_is_written_once_and_audited(client, db_session, clinic, marked):
    first = client.post("/v1/patient/consent", headers=link_headers(marked.link))
    assert (first.status_code, first.json()) == (200, {"ok": True})
    assert post(client, "/consent", marked.link).json() == {"ok": True}
    patient_id = fresh(db_session, Episode, marked.episode_id).patient_id
    rows = db_session.execute(select(Consent).where(
        Consent.patient_id == patient_id, Consent.kind == "pd_processing")).scalars().all()
    assert [(r.granted, r.source) for r in rows] == [(True, "link")]
    assert get(client, "/session", marked.link).json()["consent_required"] is False
    audit = db_session.execute(select(AuditEvent).where(
        AuditEvent.action == "patient.consent")).scalars().all()
    assert audit
    for row in audit:
        no_secrets(row.payload or "", marked.link, marked.patient_token)


# ---------- 409: порядок проверок по таблице ошибок ----------

@pytest.mark.parametrize("method,path", [("POST", "/choice"), ("GET", "/doctors"),
                                         ("GET", "/formats"), ("POST", "/requests")])
def test_consent_required_before_anything_else(client, db_session, clinic, catalog, marked,
                                               method, path):
    episode = fresh(db_session, Episode, marked.episode_id)
    put(db_session, episode, chosen_goal_id=catalog["goal"].id)  # выбор есть, согласия нет
    body = {"branch_code": None, "goal_id": catalog["goal"].id} if path == "/choice" \
        else request_body(catalog)
    expect_error(call(client, method, path, marked.link, body), 409, "consent_required")


@pytest.mark.parametrize("method,path", [("GET", "/doctors"), ("GET", "/formats"),
                                         ("POST", "/requests")])
def test_choice_required_before_doctors_formats_requests(client, clinic, catalog, marked,
                                                          method, path):
    assert post(client, "/consent", marked.link).status_code == 200
    expect_error(call(client, method, path, marked.link, request_body(catalog)), 409,
                 "choice_required")


@pytest.mark.parametrize("method,path", [("POST", "/consent"), ("POST", "/choice"),
                                         ("GET", "/doctors"), ("GET", "/formats"),
                                         ("POST", "/requests")])
def test_not_active_for_everything_but_session(client, db_session, clinic, catalog, ready,
                                               method, path):
    stop(db_session, clinic)
    body = {"branch_code": None, "goal_id": catalog["goal"].id} if path == "/choice" \
        else request_body(catalog)
    expect_error(call(client, method, path, ready.link, body), 409, "not_active")
    assert get(client, "/session", ready.link).json()["state"] == "stopped"


# ---------- POST /choice ----------

def test_choice_with_doctor_step_needs_null_branch(client, db_session, clinic, catalog, marked):
    assert post(client, "/consent", marked.link).status_code == 200
    goal = catalog["goal"].id
    expect_error(post(client, "/choice", marked.link, {"branch_code": "discuss", "goal_id": goal}),
                 422, "invalid_input")
    ok = post(client, "/choice", marked.link, {"branch_code": None, "goal_id": goal})
    assert (ok.status_code, ok.json()) == (200, {"ok": True})
    assert get(client, "/session", marked.link).json()["choice"] == {"branch_code": None,
                                                                    "goal_id": goal}
    other = catalog["goal_other"].id
    assert post(client, "/choice", marked.link,
                {"branch_code": None, "goal_id": other}).status_code == 200
    assert get(client, "/session", marked.link).json()["choice"]["goal_id"] == other
    episode = fresh(db_session, Episode, marked.episode_id)
    need_column(Episode, "chosen_goal_id")
    assert episode.chosen_goal_id == other


def test_choice_without_doctor_step_needs_known_branch(client, db_session, sign_headers, clinic,
                                                       catalog, issue):
    episode_id, _ = ingest(client, sign_headers)
    link = issue(episode_id)
    assert post(client, "/consent", link).status_code == 200
    goal = catalog["goal"].id
    for branch in (None, "unknown"):
        expect_error(post(client, "/choice", link, {"branch_code": branch, "goal_id": goal}),
                     422, "invalid_input")
    assert post(client, "/choice", link,
                {"branch_code": "discuss", "goal_id": goal}).status_code == 200
    assert get(client, "/session", link).json()["choice"] == {"branch_code": "discuss",
                                                             "goal_id": goal}
    need_column(Episode, "chosen_branch")
    assert fresh(db_session, Episode, episode_id).chosen_branch == "discuss"


def test_choice_rejects_inactive_foreign_or_unknown_goal_and_extra_fields(
        client, db_session, clinic, catalog, marked):
    assert post(client, "/consent", marked.link).status_code == 200
    foreign_clinic = Clinic(name="Чужая клиника", service_enabled=True)
    db_session.add(foreign_clinic)
    db_session.flush()
    foreign_goal = Goal(clinic_id=foreign_clinic.id, title="Чужая цель", sort_order=1)
    db_session.add(foreign_goal)
    db_session.commit()
    bodies = [
        {"branch_code": None, "goal_id": catalog["goal_off"].id},
        {"branch_code": None, "goal_id": foreign_goal.id},
        {"branch_code": None, "goal_id": "00000000-0000-0000-0000-000000000000"},
        {"branch_code": None},
        {"branch_code": None, "goal_id": catalog["goal"].id, "comment": ECHO},
        [{"branch_code": None, "goal_id": catalog["goal"].id}],
        b"{not json " + ECHO.encode(),
    ]
    for body in bodies:
        response = post(client, "/choice", marked.link, body)
        expect_error(response, 422, "invalid_input")
        assert ECHO not in response.text
    assert get(client, "/session", marked.link).json()["choice"] is None


# ---------- GET /doctors ----------

EXPECTED_ORDER = [("dev-doctor", "ordering"), ("qa-v", "visited"), ("qa-s", "visited"),
                  ("qa-t", None)]


def doctor_order(client, link, catalog, db_session) -> list[tuple[str, str | None]]:
    response = get(client, "/doctors", link)
    assert response.status_code == 200, response.text
    doctors = response.json()["doctors"]
    for item in doctors:
        assert set(item) == {"id", "name", "specialty", "photo_url", "tag"}
    by_id = {d.id: d for d in db_session.execute(select(Doctor)).scalars()}
    for item in doctors:
        assert item["name"] == by_id[item["id"]].full_name
        assert item["specialty"] == by_id[item["id"]].specialty
    return [(by_id[item["id"]].external_id, item["tag"]) for item in doctors]


def test_doctors_in_contract_order(client, db_session, clinic, catalog, ready):
    assert doctor_order(client, ready.link, catalog, db_session) == EXPECTED_ORDER


@pytest.mark.parametrize("variant", ["names", "step_retest", "other_patient_visits", "paid",
                                     "specialty", "goal_sort"])
def test_doctor_order_depends_only_on_three_sources(client, db_session, sign_headers, clinic,
                                                    catalog, issue, variant):
    """Меняем всё, кроме назначившего врача, визитов этого пациента и sort_order цели."""
    d = catalog["doctors"]
    episode_id, token = ingest(client, sign_headers)
    mark(client, episode_id, "retest" if variant == "step_retest" else "discuss",
         4 if variant == "step_retest" else None)
    link = issue(episode_id)
    add_visits(db_session, clinic, token, catalog)
    now = datetime.now(UTC)
    if variant == "names":
        for doctor, name in zip(d.values(), ("Аааев", "Бббев", "Вввев", "Гггев", "Дддев", "Еееев"),
                                strict=True):
            doctor.full_name = name
    elif variant == "other_patient_visits":
        db_session.add_all([Visit(clinic_id=clinic.id, patient_token="b6-someone-else",
                                  visit_date=now, doctor_external_id=d["therapist"].external_id),
                            Visit(clinic_id=clinic.id, patient_token="b6-someone-else",
                                  visit_date=now, doctor_external_id=d["visited_old"].external_id)])
        foreign = Clinic(name="Другая клиника", service_enabled=True)
        db_session.add(foreign)
        db_session.flush()
        db_session.add(Visit(clinic_id=foreign.id, patient_token=token, visit_date=now,
                             doctor_external_id=d["therapist"].external_id))
    elif variant == "paid":
        for visit in db_session.execute(select(Visit)).scalars():
            visit.paid_kopecks = 999999 if visit.doctor_external_id == "qa-s" else 0
    elif variant == "specialty":
        d["therapist"].specialty = "Аллерголог"
        d["visited_recent"].specialty = "Ясный"
    elif variant == "goal_sort":
        catalog["goal"].sort_order = 99
    db_session.commit()
    assert post(client, "/consent", link).status_code == 200
    assert post(client, "/choice", link,
                {"branch_code": None, "goal_id": catalog["goal"].id}).status_code == 200
    assert doctor_order(client, link, catalog, db_session) == EXPECTED_ORDER


def test_ordering_doctor_listed_once_and_only_if_active(client, db_session, clinic, catalog,
                                                       ready):
    goal_doctors = mapped("goal_doctors")
    ordering = db_session.execute(
        select(Doctor).where(Doctor.external_id == "dev-doctor")).scalar_one()
    db_session.add(goal_doctors(goal_id=catalog["goal"].id, doctor_id=ordering.id, sort_order=0))
    db_session.add(Visit(clinic_id=clinic.id, patient_token=ready.patient_token,
                         visit_date=datetime.now(UTC), doctor_external_id="dev-doctor"))
    db_session.commit()
    assert doctor_order(client, ready.link, catalog, db_session) == EXPECTED_ORDER
    put(db_session, ordering, is_active=False)
    assert doctor_order(client, ready.link, catalog, db_session) == EXPECTED_ORDER[1:]


def test_empty_doctor_list_is_200(client, db_session, sign_headers, clinic, catalog, issue):
    episode_id, _ = ingest(client, sign_headers, doctor="qa-ordering-off")
    link = issue(episode_id)
    ordering = db_session.execute(
        select(Doctor).where(Doctor.external_id == "qa-ordering-off")).scalar_one()
    put(db_session, ordering, is_active=False)
    empty_goal = Goal(clinic_id=clinic.id, title="Цель без врачей", sort_order=5)
    db_session.add(empty_goal)
    db_session.commit()
    assert post(client, "/consent", link).status_code == 200
    assert post(client, "/choice", link,
                {"branch_code": "discuss", "goal_id": empty_goal.id}).status_code == 200
    response = get(client, "/doctors", link)
    assert (response.status_code, response.json()) == (200, {"doctors": []})


# ---------- GET /formats ----------

def test_formats_and_windows_without_payment_url(client, clinic, catalog, ready):
    response = get(client, "/formats", ready.link)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"formats", "windows"}
    assert body["windows"] == WINDOWS
    formats = {item["id"]: item for item in body["formats"]}
    f = catalog["formats"]
    assert set(formats) == {f["plain"].id, f["https"].id, f["http"].id}
    for item in formats.values():
        assert set(item) == {"id", "title", "price_kopecks", "currency", "has_payment"}
    assert formats[f["https"].id] == {"id": f["https"].id, "title": "Быстрый ответ врача",
                                      "price_kopecks": 50000, "currency": "RUB",
                                      "has_payment": True}
    assert formats[f["plain"].id]["has_payment"] is False
    # допущение: адрес не https отдаётся как null, значит и оплаты для пациента нет
    assert formats[f["http"].id]["has_payment"] is False
    assert "example-clinic.ru/pay" not in response.text


# ---------- POST /requests ----------

@pytest.mark.parametrize("fmt,payment", [("plain", None), ("https", PAY_HTTPS), ("http", None)])
def test_request_created_with_outbox_and_audit(client, db_session, clinic, catalog, ready, fmt,
                                               payment):
    response = post(client, "/requests", ready.link, request_body(catalog, "visited_recent", fmt))
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"request_id", "status", "payment_url"}
    assert body["status"] == "accepted"
    assert body["payment_url"] == payment

    row = fresh(db_session, Request, body["request_id"])
    assert row.status == "new"
    assert row.episode_id == ready.episode_id
    assert row.goal_id == catalog["goal"].id
    assert row.doctor_id == catalog["doctors"]["visited_recent"].id
    assert row.format_id == catalog["formats"][fmt].id

    crm = db_session.execute(select(Outbox).where(Outbox.topic == "crm")).scalars().all()
    assert len(crm) == 1
    assert json.loads(crm[0].payload) == {"request_id": body["request_id"]}
    assert crm[0].status == "pending"
    audit = db_session.execute(select(AuditEvent).where(
        AuditEvent.action == "patient.request_created")).scalars().all()
    assert len(audit) == 1
    no_secrets(audit[0].payload or "", ready.link, ready.patient_token)

    request_view = get(client, "/session", ready.link).json()["request"]
    assert set(request_view) == {"id", "status", "doctor_name", "format_title", "window_title",
                                 "created_at"}
    assert request_view["id"] == body["request_id"]
    assert request_view["status"] == "accepted"
    assert request_view["doctor_name"] == "Яковлев Синт"
    assert request_view["format_title"] == catalog["formats"][fmt].title
    assert request_view["window_title"] == WINDOWS[0]["title"]
    assert request_view["created_at"]


@pytest.mark.parametrize("change", [
    {"doctor": "not_in_goal"}, {"doctor": "other_goal"}, {"doctor": "inactive"},
    {"doctor_id": "00000000-0000-0000-0000-000000000000"}, {"fmt": "inactive"},
    {"format_id": "00000000-0000-0000-0000-000000000000"}, {"window": "night"},
    {"drop": "window_code"}, {"extra": {"comment": ECHO}}, {"extra": {"phone": ECHO}},
    {"raw": [ECHO]}, {"raw": b"{" + ECHO.encode()},
])
def test_bad_request_is_422_without_echo_and_changes_nothing(client, db_session, clinic, catalog,
                                                             ready, change):
    kwargs = {k: change[k] for k in ("doctor", "fmt", "window") if k in change}
    body = change.get("raw") or request_body(catalog, **kwargs)
    if isinstance(body, dict):
        body = {**body, **{k: change[k] for k in ("doctor_id", "format_id") if k in change},
                **change.get("extra", {})}
        body.pop(change.get("drop", ""), None)
    response = post(client, "/requests", ready.link, body)
    expect_error(response, 422, "invalid_input")
    assert ECHO not in response.text
    assert db_session.execute(select(Request)).scalars().all() == []
    assert db_session.execute(select(Outbox).where(Outbox.topic == "crm")).scalars().all() == []


def test_one_open_request_per_episode(client, db_session, clinic, catalog, ready):
    first = post(client, "/requests", ready.link, request_body(catalog))
    assert first.status_code == 201, first.text
    for status in ("new", "sent", "in_progress"):
        put(db_session, fresh(db_session, Request, first.json()["request_id"]), status=status)
        expect_error(post(client, "/requests", ready.link, request_body(catalog, "visited_old")),
                     409, "request_exists")
    put(db_session, fresh(db_session, Request, first.json()["request_id"]), status="cancelled")
    second = post(client, "/requests", ready.link, request_body(catalog, "visited_old"))
    assert second.status_code == 201, second.text
    view = get(client, "/session", ready.link).json()["request"]
    assert view["id"] == second.json()["request_id"]  # последняя незавершённая, не отменённая
    put(db_session, fresh(db_session, Request, second.json()["request_id"]), status="booked")
    view = get(client, "/session", ready.link).json()["request"]
    assert (view["id"], view["status"]) == (second.json()["request_id"], "booked")


@pytest.mark.parametrize("stored,shown", [("new", "accepted"), ("sent", "accepted"),
                                          ("in_progress", "in_progress"), ("booked", "booked"),
                                          ("cancelled", "cancelled")])
def test_request_status_is_simplified_for_patient(client, db_session, clinic, catalog, ready,
                                                  stored, shown):
    created = post(client, "/requests", ready.link, request_body(catalog))
    assert created.status_code == 201, created.text
    put(db_session, fresh(db_session, Request, created.json()["request_id"]), status=stored)
    assert get(client, "/session", ready.link).json()["request"]["status"] == shown


# ---------- ПДн: ответы, аудит, outbox, журналы ----------

def test_no_phone_token_or_link_in_responses_audit_outbox_and_logs(client, db_session, clinic,
                                                                   catalog, marked, caplog):
    caplog.set_level(logging.DEBUG)
    add_visits(db_session, clinic, marked.patient_token, catalog)
    responses = [get(client, "/session", marked.link), post(client, "/consent", marked.link),
                 post(client, "/choice", marked.link,
                      {"branch_code": None, "goal_id": catalog["goal"].id}),
                 get(client, "/doctors", marked.link), get(client, "/formats", marked.link),
                 post(client, "/requests", marked.link, request_body(catalog)),
                 get(client, "/session", marked.link),
                 post(client, "/requests", marked.link, request_body(catalog)),
                 get(client, "/session", "x" * 20)]
    assert [r.status_code for r in responses] == [200, 200, 200, 200, 200, 201, 200, 409, 404]
    for response in responses:
        no_secrets(response.text, marked.link, marked.patient_token)
        assert "patient_token" not in response.text
    for row in db_session.execute(select(AuditEvent)).scalars():
        no_secrets(row.payload or "", marked.link)
        assert row.entity_id != marked.link
    for row in db_session.execute(select(Outbox)).scalars():
        no_secrets(row.payload, marked.link, marked.patient_token)
    no_secrets(caplog.text, marked.link, marked.patient_token)


def test_session_has_no_other_patients_or_health_fields(client, sign_headers, clinic, catalog,
                                                        ready):
    other_id, other_token = ingest(client, sign_headers, n=1)
    text = get(client, "/session", ready.link).text
    assert other_id not in text and other_token not in text
    for word in ("group", "control", "diagnos", "result", "abnormal", "value"):
        assert f'"{word}' not in text.lower()


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
def test_two_simultaneous_requests_give_one(db_session, clinic, catalog, ready, parallel):
    with TestClient(fastapi_app) as c1, TestClient(fastapi_app) as c2:
        codes = run_together(
            lambda: post(c1, "/requests", ready.link, request_body(catalog)).status_code,
            lambda: post(c2, "/requests", ready.link,
                         request_body(catalog, "visited_old")).status_code)
    assert sorted(codes) == [201, 409]
    db_session.expire_all()
    assert len(db_session.execute(select(Request)).scalars().all()) == 1
    assert len(db_session.execute(select(Outbox).where(
        Outbox.topic == "crm")).scalars().all()) == 1


def test_contract_has_no_link_issuing_endpoint():
    paths = fastapi_app.openapi()["paths"]
    patient = {p for p in paths if p.startswith("/v1/patient")}
    assert patient == {"/v1/patient/session", "/v1/patient/consent", "/v1/patient/choice",
                       "/v1/patient/doctors", "/v1/patient/formats", "/v1/patient/requests"}
    assert not any("link" in p for p in paths)

