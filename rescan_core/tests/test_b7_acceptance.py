"""Приёмочные тесты B7 (заявки в CRM) по разделу «Контракты» задания 19.

Чёрный ящик: заявка и запись `outbox` (topic = crm) создаются через ORM — так B7
проверяется независимо от HTTP-пути B6. Отправка — контрактная функция
`deliver_pending(session, now, send)` из `app.services.crm_service`, приёмники —
свои фейковые `http.server` на 127.0.0.1 с портом 0 (во внешнюю сеть тесты не ходят).
Статусы обратно — через HTTP: `POST /v1/crm/status` с подписью и
`POST /v1/admin/requests/{id}/status` с токеном администратора.

Настройки `crm_targets`, `notify_targets`, `crm_status_secret` контракт берёт только из
окружения: тест кладёт JSON в переменные окружения, разбирает их классом `Settings` и
переносит разобранные значения в общий объект настроек (тип полей тесту не важен).
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db.models import (
    AuditEvent,
    Clinic,
    Doctor,
    Episode,
    Format,
    Goal,
    Outbox,
    Patient,
    Request,
)
from app.security.hmac import compute_signature
from app.services.group_service import Group, assign_group

PHONE = "+7 (900) 000-00-71"
PHONE_NUMBER = "79000000071"  # так телефон хранится после приёма события (только цифры)
PHONE_DIGITS = ("9000000071", "79000000071", "000-00-71")
STATUS_SECRET = "qa-status-secret-" + "s" * 32
WEBHOOK_SECRET = "qa-webhook-secret-" + "w" * 32
NOTIFY_SECRET = "qa-notify-secret-" + "n" * 32
WINDOWS = [{"code": "morning", "title": "Утром, 8:00–12:00"},
           {"code": "evening", "title": "Вечером, 17:00–21:00"}]
PATIENT_SETTINGS = {
    "phone": "+7 000 000-00-00", "privacy_url": "https://example-clinic.ru/privacy",
    "timezone": "Europe/Moscow",
    "branches": [{"code": "discuss", "title": "Обсудить", "hint": "Синтетика"}],
    "windows": WINDOWS, "texts": {"p1.active.title": "Синтетика"},
}
GOAL_TITLE = "Синтетическая цель CRM"
DOCTOR_NAME = "Синтетический Кардиолог"
FORMAT_TITLE = "Приём в клинике"
RETRY_MINUTES = [1, 5, 15, 60]
ADMIN = {"X-Staff-Token": "dev-admin-token"}
DOCTOR = {"X-Staff-Token": "dev-doctor-token"}
WEBHOOK_KEYS = {"request_id", "clinic_id", "patient_token", "phone", "doctor", "format", "window",
                "goal", "created_at"}
NOTIFY_KEYS = {"request_id", "clinic_id", "phone", "doctor", "format", "window", "goal", "reason"}


# ---------- фейковый приёмник ----------

class FakeReceiver:
    """HTTP-приёмник на 127.0.0.1:0. Запоминает запросы, отвечает по очереди `replies`."""

    def __init__(self, default=(200, {})) -> None:
        self.received: list[dict] = []
        self.replies: list[tuple[int, object]] = []
        self.default = default
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                receiver.received.append({"path": self.path, "headers": dict(self.headers),
                                          "raw": raw})
                status, body = receiver.replies.pop(0) if receiver.replies else receiver.default
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def bodies(self) -> list[dict]:
        return [json.loads(item["raw"]) for item in self.received]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def crm():
    receiver = FakeReceiver()
    yield receiver
    receiver.close()


@pytest.fixture
def notify():
    receiver = FakeReceiver()
    yield receiver
    receiver.close()


def closed_port_url() -> str:
    """Адрес, где никто не слушает: сетевая ошибка без выхода наружу."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


# ---------- настройки и данные ----------

B7_FIELDS = ("crm_targets", "notify_targets", "crm_status_secret")


@pytest.fixture
def configure(monkeypatch, clinic):
    """Настройки B7 из окружения → разбор `Settings()` → общий объект настроек."""

    def _configure(crm: dict | None = None, notify: dict | None = None) -> None:
        monkeypatch.setenv("CRM_TARGETS", json.dumps(crm or {}))
        monkeypatch.setenv("NOTIFY_TARGETS", json.dumps(notify or {}))
        monkeypatch.setenv("CRM_STATUS_SECRET", STATUS_SECRET)
        missing = [name for name in B7_FIELDS if name not in Settings.model_fields]
        if missing:
            pytest.fail(f"нет настроек B7 в app.config.Settings: {', '.join(missing)}")
        parsed = Settings(_env_file=None)
        current = get_settings()
        for name in B7_FIELDS:
            monkeypatch.setattr(current, name, getattr(parsed, name))

    _configure()
    return _configure


def bitrix(receiver, path="/rest/1/qa") -> dict:
    return {"kind": "bitrix24", "url": receiver.url + path}


def webhook(receiver, path="/hook", secret=WEBHOOK_SECRET) -> dict:
    return {"kind": "webhook", "url": receiver.url + path, "secret": secret}


def need_column(model, name: str) -> None:
    if name not in model.__table__.columns:
        pytest.fail(f"нет колонки {model.__tablename__}.{name}: ждём миграцию и модели B6")


@pytest.fixture
def clinic(db_session, monkeypatch):
    clinic = db_session.execute(select(Clinic)).scalar_one()
    monkeypatch.setattr(get_settings(), "mis_clinic_id", clinic.id)
    return clinic


@pytest.fixture
def delivery(db_session, clinic, configure):
    """Для отправки: окна клиники (название окна берётся из clinics.patient_settings, B6)."""
    need_column(Clinic, "patient_settings")
    clinic.patient_settings = json.dumps(PATIENT_SETTINGS, ensure_ascii=False)
    db_session.commit()
    return configure


@pytest.fixture
def catalog(db_session, clinic):
    doctor = Doctor(clinic_id=clinic.id, external_id="qa-crm-doc", full_name=DOCTOR_NAME,
                    specialty="Кардиолог")
    fmt = Format(clinic_id=clinic.id, title=FORMAT_TITLE, price_kopecks=250000)
    goal = Goal(clinic_id=clinic.id, title=GOAL_TITLE, sort_order=1)
    db_session.add_all([doctor, fmt, goal])
    db_session.commit()
    return {"doctor": doctor, "format": fmt, "goal": goal}


def token_in(group: Group, n: int = 0) -> str:
    found = (f"b7-pt-{i}" for i in range(5000) if assign_group(f"b7-pt-{i}") == group)
    for _ in range(n):
        next(found)
    return next(found)


def ingest(client, sign_headers, n: int = 0) -> tuple[str, str]:
    """Эпизод основной группы через `/v1/mis/results-ready`: так появляется contacts."""
    token = token_in(Group.MAIN, n)
    body = json.dumps({
        "event_id": f"b7-evt-{n}", "branch_id": "br-1", "patient_token": token, "phone": PHONE,
        "ordering_doctor_id": "dev-doctor", "ready_at": "2026-10-14T09:00:00+03:00",
        "marketing_consent": True,
    }).encode()
    response = client.post("/v1/mis/results-ready", content=body, headers=sign_headers(body))
    assert response.status_code == 202, response.text
    return response.json()["episode_id"], token


class Made:
    def __init__(self, request_id: str, outbox_id: str, patient_token: str, episode_id: str):
        self.request_id = request_id
        self.outbox_id = outbox_id
        self.patient_token = patient_token
        self.episode_id = episode_id


@pytest.fixture
def make(db_session, client, sign_headers, catalog):
    """Заявка как после `POST /v1/patient/requests`: requests(new) + outbox(crm, {request_id})."""
    counter = iter(range(100))

    def _make(status: str = "new", crm_request_id: str | None = None,
              with_outbox: bool = True) -> Made:
        episode_id, token = ingest(client, sign_headers, next(counter))
        episode = db_session.get(Episode, episode_id)
        request = Request(episode_id=episode_id, patient_id=episode.patient_id,
                          doctor_id=catalog["doctor"].id, format_id=catalog["format"].id,
                          goal_id=catalog["goal"].id, window="morning", status=status,
                          crm_request_id=crm_request_id)
        db_session.add(request)
        db_session.flush()
        outbox = Outbox(topic="crm", payload=json.dumps({"request_id": request.id}),
                        status="pending")
        if with_outbox:
            db_session.add(outbox)
        db_session.commit()
        return Made(request.id, outbox.id if with_outbox else "", token, episode_id)

    return _make


def default_send():
    """`send` по умолчанию. Контракт называет параметр, но не саму функцию HTTP-отправки:
    берём значение по умолчанию параметра `send`, иначе явную функцию из crm_transports."""
    from app.services import crm_service

    param = inspect.signature(crm_service.deliver_pending).parameters.get("send")
    if param is not None and param.default is not inspect.Parameter.empty:
        return param.default
    try:
        from app.services import crm_transports
    except ImportError:
        crm_transports = None
    for module in (crm_transports, crm_service):
        for name in ("send", "http_send", "send_http", "post_json", "http_post", "default_send"):
            candidate = getattr(module, name, None)
            if callable(candidate):
                return candidate
    pytest.fail("deliver_pending(session, now, send): нет функции HTTP-отправки по умолчанию — "
                "уточнить у координатора, что передавать в send")


def deliver(session, now: datetime | None = None):
    from app.services.crm_service import deliver_pending

    result = deliver_pending(session, now or datetime.now(UTC), default_send())
    session.commit()
    session.expire_all()
    return result


def fresh(session, model, key):
    session.expire_all()
    return session.get(model, key)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def audits(session, action: str) -> list[AuditEvent]:
    session.expire_all()
    return session.execute(select(AuditEvent).where(AuditEvent.action == action)).scalars().all()


def outbox_rows(session, topic: str) -> list[Outbox]:
    session.expire_all()
    return session.execute(select(Outbox).where(Outbox.topic == topic)).scalars().all()


def no_pii(blob: str, *extra: str) -> None:
    for item in PHONE_DIGITS + tuple(x for x in extra if x):
        assert item not in blob


def check_signature(received: dict, secret: str) -> None:
    headers = {k.lower(): v for k, v in received["headers"].items()}
    timestamp = headers["x-rescan-timestamp"]
    assert abs(int(timestamp) - time.time()) < 120
    assert headers["x-rescan-signature"] == compute_signature(received["raw"], secret, timestamp)


def digits(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


# ---------- Битрикс24 ----------

def test_bitrix24_lead_fields_and_success(db_session, clinic, delivery, crm, make, caplog):
    caplog.set_level(logging.DEBUG)
    crm.replies.append((200, {"result": 4242}))
    delivery(crm={clinic.id: bitrix(crm)})
    made = make()
    deliver(db_session)

    assert [r["path"] for r in crm.received] == ["/rest/1/qa/crm.lead.add.json"]
    body = crm.bodies()[0]
    fields = body.get("fields", body)  # допущение: поля лида на верхнем уровне или в "fields"
    assert fields["TITLE"] == f"Заявка rescan: {GOAL_TITLE}"
    assert [{**p, "VALUE": digits(p["VALUE"])} for p in fields["PHONE"]] == [
        {"VALUE": PHONE_NUMBER, "VALUE_TYPE": "MOBILE"}]
    for part in (DOCTOR_NAME, FORMAT_TITLE, WINDOWS[0]["title"]):
        assert part in fields["COMMENTS"]
    assert fields["SOURCE_DESCRIPTION"] == "rescan"

    request = fresh(db_session, Request, made.request_id)
    assert (request.status, request.crm_request_id) == ("sent", "4242")
    outbox = fresh(db_session, Outbox, made.outbox_id)
    assert outbox.status == "done"
    assert outbox.processed_at is not None
    sent = audits(db_session, "crm.request_sent")
    assert len(sent) == 1
    no_pii(sent[0].payload or "", crm.url, "127.0.0.1")
    no_pii(caplog.text)
    for row in db_session.execute(select(Outbox)).scalars():
        no_pii(row.payload)


def test_bitrix24_answer_without_result_is_failure(db_session, clinic, delivery, crm, make):
    crm.replies.append((200, {"error": "синтетическая ошибка"}))
    delivery(crm={clinic.id: bitrix(crm)})
    made = make()
    now = datetime.now(UTC)
    deliver(db_session, now)
    outbox = fresh(db_session, Outbox, made.outbox_id)
    assert (outbox.status, outbox.attempts) == ("pending", 1)
    assert aware(outbox.available_at) == now + timedelta(minutes=1)
    assert fresh(db_session, Request, made.request_id).status == "new"


# ---------- универсальный вебхук ----------

@pytest.mark.parametrize("reply,crm_id", [((200, {"crm_request_id": "ext-77"}), "ext-77"),
                                          ((200, {}), None), ((202, b""), None)])
def test_webhook_body_signature_and_success(db_session, clinic, delivery, crm, make, catalog,
                                            caplog, reply, crm_id):
    caplog.set_level(logging.DEBUG)
    crm.replies.append(reply)
    delivery(crm={clinic.id: webhook(crm)})
    made = make()
    deliver(db_session)

    assert [r["path"] for r in crm.received] == ["/hook"]
    check_signature(crm.received[0], WEBHOOK_SECRET)
    body = crm.bodies()[0]
    assert set(body) == WEBHOOK_KEYS
    assert body["request_id"] == made.request_id
    assert body["clinic_id"] == clinic.id
    assert body["patient_token"] == made.patient_token
    assert digits(body["phone"]) == PHONE_NUMBER
    assert body["doctor"] == {"external_id": "qa-crm-doc", "name": DOCTOR_NAME}
    assert body["format"] == {"title": FORMAT_TITLE, "price_kopecks": 250000}
    assert body["window"] == WINDOWS[0]  # допущение: requests.window хранит код окна
    assert body["goal"] == {"title": GOAL_TITLE}
    assert body["created_at"]

    request = fresh(db_session, Request, made.request_id)
    assert (request.status, request.crm_request_id) == ("sent", crm_id)
    assert fresh(db_session, Outbox, made.outbox_id).status == "done"
    assert len(audits(db_session, "crm.request_sent")) == 1
    no_pii(caplog.text, WEBHOOK_SECRET)
    for row in db_session.execute(select(AuditEvent)).scalars():
        no_pii(row.payload or "", crm.url, WEBHOOK_SECRET)


def test_only_due_pending_crm_records_are_taken(db_session, clinic, delivery, crm, make):
    delivery(crm={clinic.id: webhook(crm)})
    now = datetime.now(UTC)
    later = make()
    row = fresh(db_session, Outbox, later.outbox_id)
    row.available_at = now + timedelta(minutes=5)
    sms = Outbox(topic="sms", payload=json.dumps({"request_id": later.request_id}),
                 status="pending")
    db_session.add(sms)
    db_session.commit()
    deliver(db_session, now)
    assert crm.received == []
    assert fresh(db_session, Outbox, later.outbox_id).status == "pending"
    assert fresh(db_session, Outbox, sms.id).status == "pending"
    deliver(db_session, now + timedelta(minutes=5))
    assert len(crm.received) == 1


# ---------- ретраи и запасной канал ----------

@pytest.mark.parametrize("failure", ["http_500", "network", "bitrix_no_result"])
def test_retry_schedule_then_failed_and_notify(db_session, clinic, delivery, crm, notify, make,
                                               caplog, failure):
    caplog.set_level(logging.DEBUG)
    target = {"http_500": lambda: webhook(crm), "bitrix_no_result": lambda: bitrix(crm),
              "network": lambda: {"kind": "webhook", "url": closed_port_url() + "/hook",
                                  "secret": WEBHOOK_SECRET}}[failure]()
    crm.default = (500, {}) if failure == "http_500" else (200, {})
    delivery(crm={clinic.id: target},
              notify={clinic.id: {"url": notify.url + "/admin", "secret": NOTIFY_SECRET}})
    made = make()
    now = datetime.now(UTC)
    for attempt, minutes in enumerate(RETRY_MINUTES, start=1):
        deliver(db_session, now)
        outbox = fresh(db_session, Outbox, made.outbox_id)
        assert (outbox.status, outbox.attempts) == ("pending", attempt)
        assert aware(outbox.available_at) == now + timedelta(minutes=minutes)
        sent_before = len(crm.received)
        deliver(db_session, now + timedelta(minutes=minutes) - timedelta(seconds=1))
        assert len(crm.received) == sent_before  # раньше срока не трогаем
        assert fresh(db_session, Outbox, made.outbox_id).attempts == attempt
        now += timedelta(minutes=minutes)
    deliver(db_session, now)
    outbox = fresh(db_session, Outbox, made.outbox_id)
    assert (outbox.status, outbox.attempts) == ("failed", 5)
    assert len(audits(db_session, "crm.request_failed")) == 1
    notices = outbox_rows(db_session, "notify")
    assert len(notices) == 1
    assert json.loads(notices[0].payload) == {"request_id": made.request_id}

    deliver(db_session, now)
    deliver(db_session, now + timedelta(minutes=1))
    assert [r["path"] for r in notify.received] == ["/admin"]
    check_signature(notify.received[0], NOTIFY_SECRET)
    body = notify.bodies()[0]
    assert set(body) == NOTIFY_KEYS
    assert body["reason"] == "crm_failed"
    assert body["request_id"] == made.request_id
    assert digits(body["phone"]) == PHONE_NUMBER
    if failure != "network":
        assert len(crm.received) == 5
    for row in db_session.execute(select(Outbox)).scalars():
        no_pii(row.payload)
    for row in db_session.execute(select(AuditEvent)).scalars():
        no_pii(row.payload or "", crm.url, notify.url, NOTIFY_SECRET)
    no_pii(caplog.text, NOTIFY_SECRET, WEBHOOK_SECRET)


def test_clinic_without_crm_goes_straight_to_notify(db_session, clinic, delivery, crm, notify,
                                                    make):
    delivery(crm={}, notify={clinic.id: {"url": notify.url + "/admin", "secret": NOTIFY_SECRET}})
    made = make()
    now = datetime.now(UTC)
    deliver(db_session, now)
    deliver(db_session, now)
    assert crm.received == []
    assert len(notify.received) == 1
    check_signature(notify.received[0], NOTIFY_SECRET)
    body = notify.bodies()[0]
    assert set(body) == NOTIFY_KEYS
    assert (body["reason"], body["request_id"], body["clinic_id"]) == ("no_crm", made.request_id,
                                                                       clinic.id)
    assert body["doctor"]["name"] == DOCTOR_NAME
    assert [json.loads(o.payload) for o in outbox_rows(db_session, "notify")] == [
        {"request_id": made.request_id}]


def test_no_crm_and_no_notify_is_failed_with_audit_and_log(db_session, clinic, delivery, crm,
                                                           notify, make, caplog):
    caplog.set_level(logging.DEBUG)
    delivery(crm={}, notify={})
    make()
    now = datetime.now(UTC)
    deliver(db_session, now)
    deliver(db_session, now + timedelta(minutes=1))
    assert crm.received == [] and notify.received == []
    rows = db_session.execute(select(Outbox)).scalars().all()
    assert any(row.status == "failed" for row in rows)
    assert not any(row.status == "pending" and row.topic in {"crm", "notify"} for row in rows)
    assert len(audits(db_session, "crm.no_channel")) >= 1
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    no_pii(caplog.text)


def test_opted_out_patient_is_not_sent(db_session, clinic, delivery, crm, notify, make):
    delivery(crm={clinic.id: webhook(crm)},
              notify={clinic.id: {"url": notify.url + "/admin", "secret": NOTIFY_SECRET}})
    made = make()
    patient = db_session.get(Patient, fresh(db_session, Episode, made.episode_id).patient_id)
    patient.opted_out = True
    db_session.commit()
    deliver(db_session)
    deliver(db_session)
    assert crm.received == [] and notify.received == []
    assert fresh(db_session, Request, made.request_id).status == "cancelled"
    assert len(audits(db_session, "crm.skipped_opted_out")) == 1


# ---------- статус из CRM ----------

def status_call(client, body, *, secret=STATUS_SECRET, ts=None, raw: bytes | None = None,
                signed: bool = True):
    payload = raw if raw is not None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        timestamp = str(ts if ts is not None else int(time.time()))
        headers |= {"X-Rescan-Signature": compute_signature(payload, secret, timestamp),
                    "X-Rescan-Timestamp": timestamp}
    return client.post("/v1/crm/status", content=payload, headers=headers)


def changed(session) -> int:
    return len(audits(session, "crm.status_changed"))


@pytest.mark.parametrize("start,target", [("sent", "in_progress"), ("sent", "cancelled"),
                                          ("new", "cancelled"), ("in_progress", "booked"),
                                          ("in_progress", "cancelled")])
@pytest.mark.parametrize("key", ["request_id", "crm_request_id"])
def test_crm_status_transitions(client, db_session, configure, make, start, target, key):
    made = make(status=start, crm_request_id="ext-1", with_outbox=False)
    ref = made.request_id if key == "request_id" else "ext-1"
    response = status_call(client, {key: ref, "status": target})
    assert response.status_code == 200, response.text
    assert response.json() == {"request_id": made.request_id, "status": target}
    assert fresh(db_session, Request, made.request_id).status == target
    rows = audits(db_session, "crm.status_changed")
    assert len(rows) == 1
    assert "crm" in " ".join(str(x) for x in (rows[0].actor_id, rows[0].role, rows[0].payload))


@pytest.mark.parametrize("status", ["in_progress", "booked", "cancelled"])
def test_same_status_again_is_200_without_change(client, db_session, configure, make, status):
    made = make(status=status, with_outbox=False)
    before = changed(db_session)
    response = status_call(client, {"request_id": made.request_id, "status": status})
    assert (response.status_code, response.json()) == (200, {"request_id": made.request_id,
                                                            "status": status})
    assert fresh(db_session, Request, made.request_id).status == status
    assert changed(db_session) == before


@pytest.mark.parametrize("start,target", [("booked", "in_progress"), ("booked", "cancelled"),
                                          ("cancelled", "in_progress"), ("cancelled", "booked")])
def test_final_statuses_do_not_change(client, db_session, configure, make, start, target):
    made = make(status=start, with_outbox=False)
    response = status_call(client, {"request_id": made.request_id, "status": target})
    assert response.status_code == 409
    assert fresh(db_session, Request, made.request_id).status == start
    assert changed(db_session) == 0


def test_crm_status_signature(client, db_session, configure, make):
    made = make(status="sent", with_outbox=False)
    body = {"request_id": made.request_id, "status": "in_progress"}
    assert status_call(client, body, signed=False).status_code == 401
    assert status_call(client, body, secret="wrong-" + STATUS_SECRET).status_code == 401
    assert status_call(client, body, secret="dev-only-change-me").status_code == 401  # секрет МИС
    assert status_call(client, body, ts=int(time.time()) - 3600).status_code == 401
    timestamp = str(int(time.time()))
    other = json.dumps({**body, "status": "booked"}).encode()
    response = client.post("/v1/crm/status", content=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "X-Rescan-Timestamp": timestamp,
        "X-Rescan-Signature": compute_signature(other, STATUS_SECRET, timestamp)})
    assert response.status_code == 401
    assert fresh(db_session, Request, made.request_id).status == "sent"


def test_crm_status_unknown_request_is_404(client, configure, make):
    make(status="sent", crm_request_id="ext-1", with_outbox=False)
    for body in ({"request_id": "00000000-0000-0000-0000-000000000000", "status": "booked"},
                 {"crm_request_id": "ext-404", "status": "booked"}):
        assert status_call(client, body).status_code == 404


@pytest.mark.parametrize("body", [
    {"request_id": "R", "crm_request_id": "ext-1", "status": "booked"},
    {"status": "booked"},
    {"request_id": "R", "status": "sent"},
    {"request_id": "R", "status": "new"},
    {"request_id": "R", "status": "done"},
    {"request_id": "R", "status": "booked", "comment": "лишнее"},
    {"request_id": "R"},
    [{"request_id": "R", "status": "booked"}],
])
def test_crm_status_bad_body_is_422(client, db_session, configure, make, body):
    made = make(status="sent", crm_request_id="ext-1", with_outbox=False)
    if isinstance(body, dict) and body.get("request_id") == "R":
        body = {**body, "request_id": made.request_id}
    assert status_call(client, body).status_code == 422
    assert status_call(client, None, raw=b"{not json").status_code == 422
    assert fresh(db_session, Request, made.request_id).status == "sent"


# ---------- ручная отметка администратором ----------

def admin_call(client, request_id: str, body, headers=ADMIN):
    return client.post(f"/v1/admin/requests/{request_id}/status",
                       content=json.dumps(body).encode(),
                       headers={**headers, "Content-Type": "application/json"})


def test_admin_marks_status_with_audit(client, db_session, configure, make):
    made = make(status="sent", with_outbox=False)
    response = admin_call(client, made.request_id, {"status": "booked"})
    assert response.status_code == 200, response.text
    assert fresh(db_session, Request, made.request_id).status == "booked"
    rows = audits(db_session, "crm.status_changed")
    assert [row.actor_id for row in rows] == ["dev-admin"]
    assert admin_call(client, made.request_id, {"status": "booked"}).status_code == 200
    assert admin_call(client, made.request_id, {"status": "in_progress"}).status_code == 409
    assert admin_call(client, made.request_id, {"status": "booked", "x": 1}).status_code == 422
    assert admin_call(client, made.request_id, {"status": "sent"}).status_code == 422


def test_admin_status_access(client, db_session, configure, make, clinic):
    made = make(status="sent", with_outbox=False)
    assert admin_call(client, made.request_id, {"status": "booked"}, {}).status_code == 401
    assert admin_call(client, made.request_id, {"status": "booked"}, DOCTOR).status_code == 403
    missing = admin_call(client, "00000000-0000-0000-0000-000000000000", {"status": "booked"})
    assert missing.status_code == 404

    foreign = Clinic(name="Чужая клиника", service_enabled=True)
    db_session.add(foreign)
    db_session.flush()
    patient = Patient(clinic_id=foreign.id, patient_token="b7-foreign", group="main")
    db_session.add(patient)
    db_session.flush()
    request = Request(patient_id=patient.id, status="sent")
    db_session.add(request)
    db_session.commit()
    response = admin_call(client, request.id, {"status": "booked"})
    assert (response.status_code, response.json()) == (404, missing.json())
    assert fresh(db_session, Request, request.id).status == "sent"
    assert fresh(db_session, Request, made.request_id).status == "sent"


# ---------- настройки в проде ----------

def production(**overrides) -> dict:
    values = {
        "environment": "production",
        "mis_hmac_secret": "test-hmac-" + "a" * 32, "pilot_salt": "test-pilot-" + "b" * 32,
        "contact_encryption_key": "test-key-" + "c" * 32,
        "contact_hash_salt": "test-hash-" + "d" * 32, "staff_tokens": {},
        "mis_clinic_id": "test-clinic",
    }
    return {**values, **overrides}


@pytest.fixture
def prod_env(monkeypatch):
    def _env(crm: dict | None = None, notify: dict | None = None,
             status_secret: str = STATUS_SECRET) -> None:
        monkeypatch.setenv("PATIENT_LINK_SECRET", "qa-link-secret-" + "l" * 32)
        monkeypatch.setenv("CRM_TARGETS", json.dumps(crm or {}))
        monkeypatch.setenv("NOTIFY_TARGETS", json.dumps(notify or {}))
        monkeypatch.setenv("CRM_STATUS_SECRET", status_secret)

    return _env


GOOD_CRM = {"c1": {"kind": "webhook", "url": "https://crm.example-clinic.ru/hook",
                   "secret": WEBHOOK_SECRET},
            "c2": {"kind": "bitrix24", "url": "https://example-clinic.bitrix24.ru/rest/1/x"}}
GOOD_NOTIFY = {"c1": {"url": "https://notify.example-clinic.ru/admin", "secret": NOTIFY_SECRET}}


def test_production_accepts_https_targets_and_long_secrets(prod_env):
    prod_env(GOOD_CRM, GOOD_NOTIFY)
    assert Settings(_env_file=None, **production()).environment == "production"


@pytest.mark.parametrize("crm,notify,status_secret,leak", [
    ({"c1": {**GOOD_CRM["c1"], "url": "http://crm.example-clinic.ru/hook"}}, GOOD_NOTIFY,
     STATUS_SECRET, "crm.example-clinic.ru"),
    ({"c1": {"kind": "webhook", "url": "https://crm.example-clinic.ru/hook"}}, GOOD_NOTIFY,
     STATUS_SECRET, "crm.example-clinic.ru"),
    ({"c1": {**GOOD_CRM["c1"], "secret": "short-secret"}}, GOOD_NOTIFY, STATUS_SECRET,
     "short-secret"),
    ({"c1": {**GOOD_CRM["c1"], "secret": "dev-" + "x" * 40}}, GOOD_NOTIFY, STATUS_SECRET,
     "dev-" + "x" * 40),
    (GOOD_CRM, {"c1": {**GOOD_NOTIFY["c1"], "url": "http://notify.example-clinic.ru/a"}},
     STATUS_SECRET, "notify.example-clinic.ru"),
    (GOOD_CRM, GOOD_NOTIFY, "short-status", "short-status"),
    (GOOD_CRM, GOOD_NOTIFY, "dev-" + "y" * 40, "dev-" + "y" * 40),
], ids=["crm-http", "webhook-no-secret", "webhook-short-secret", "webhook-dev-secret",
        "notify-http", "status-secret-short", "status-secret-dev"])
def test_production_rejects_bad_targets_without_printing_them(prod_env, crm, notify,
                                                              status_secret, leak):
    prod_env(crm, notify, status_secret)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **production())
    assert leak not in str(error.value)
    assert WEBHOOK_SECRET not in str(error.value)


def test_local_allows_fake_receiver_on_loopback(monkeypatch):
    monkeypatch.setenv("CRM_TARGETS", json.dumps(
        {"c1": {"kind": "webhook", "url": "http://127.0.0.1:9/hook", "secret": "x"}}))
    monkeypatch.setenv("NOTIFY_TARGETS", json.dumps({"c1": {"url": "http://127.0.0.1:9/n",
                                                            "secret": "y"}}))
    for environment in ("local", "test"):
        assert Settings(_env_file=None, environment=environment).environment == environment


# ---------- гонка (PostgreSQL) ----------

needs_postgres = pytest.mark.skipif(not os.environ.get("RESCAN_TEST_DATABASE_URL"),
                                    reason="гонки проверяются на PostgreSQL")


@needs_postgres
def test_two_simultaneous_deliveries_send_once(db_session, clinic, delivery, crm, make):
    from app.services.crm_service import deliver_pending

    delivery(crm={clinic.id: webhook(crm)})
    made = make()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    send = default_send()
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def job():
        session = factory()
        try:
            barrier.wait()
            deliver_pending(session, datetime.now(UTC), send)
            session.commit()
        except Exception as exc:  # ошибку покажет assert ниже
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=job) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert errors == []
    assert len(crm.received) == 1
    assert fresh(db_session, Outbox, made.outbox_id).status == "done"
    assert fresh(db_session, Request, made.request_id).status == "sent"
