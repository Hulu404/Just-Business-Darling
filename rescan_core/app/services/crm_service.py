"""B7: очередь CRM, запасной канал и переходы статуса заявки."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
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
from app.schemas.crm import StatusResult
from app.security.crypto import decrypt_phone
from app.services import audit
from app.services.crm_transports import DeliveryError, http_send

Send = Callable[[str, dict[str, str], dict[str, Any]], str | None]
RETRY_MINUTES = (1, 5, 15, 60)
TRANSITIONS = {
    "new": {"cancelled"},
    "sent": {"in_progress", "cancelled"},
    "in_progress": {"booked", "cancelled"},
    "booked": set(),
    "cancelled": set(),
}
logger = logging.getLogger(__name__)


def _utc(now: datetime) -> datetime:
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)


def _record(session: Session, action: str, request_id: str) -> None:
    audit.record(session, action=action, actor_id="system", entity="request", entity_id=request_id)


def _notify(session: Session, request_id: str, now: datetime) -> None:
    session.add(Outbox(topic="notify", payload=json.dumps({"request_id": request_id}),
                      available_at=now))
    session.flush()


def _window_title(clinic: Clinic, code: str | None) -> str | None:
    """Подпись окна из clinics.patient_settings (B6); нет настроек — None, без догадок."""
    # До слияния B6 колонки нет; битые настройки не мешают доставке заявки.
    raw_settings = getattr(clinic, "patient_settings", None)
    if not raw_settings or code is None:
        return None
    try:
        windows = json.loads(raw_settings).get("windows", [])
    except (ValueError, TypeError, AttributeError):
        return None
    if not isinstance(windows, list):
        return None
    for window in windows:
        if isinstance(window, dict) and window.get("code") == code:
            title = window.get("title")
            return title if isinstance(title, str) else None
    return None


def _payload(
    session: Session, request: Request, patient: Patient, clinic: Clinic,
) -> dict[str, Any]:
    doctor = session.get(Doctor, request.doctor_id) if request.doctor_id else None
    format_ = session.get(Format, request.format_id) if request.format_id else None
    goal = session.get(Goal, request.goal_id) if request.goal_id else None
    if doctor is None or format_ is None or goal is None:
        raise DeliveryError()
    if any(item.clinic_id != clinic.id for item in (doctor, format_, goal)):
        raise DeliveryError()
    contact = session.scalar(select(Contact).where(Contact.patient_id == patient.id)
                             .order_by(Contact.updated_at.desc(), Contact.id).limit(1))
    if contact is None:
        raise DeliveryError()
    return {
        "request_id": request.id, "clinic_id": clinic.id, "patient_token": patient.patient_token,
        "phone": decrypt_phone(contact.phone_enc),
        "doctor": {"external_id": doctor.external_id, "name": doctor.full_name},
        "format": {"title": format_.title, "price_kopecks": format_.price_kopecks},
        "window": {"code": request.window, "title": _window_title(clinic, request.window)},
        "goal": {"title": goal.title}, "created_at": _utc(request.created_at).isoformat(),
    }


def _failed(session: Session, row: Outbox, request_id: str, now: datetime) -> None:
    row.attempts += 1
    if row.attempts < 5:
        row.status = "pending"
        row.available_at = now + timedelta(minutes=RETRY_MINUTES[row.attempts - 1])
        return
    row.status, row.processed_at = "failed", now
    if row.topic == "crm":
        _record(session, "crm.request_failed", request_id)
        _notify(session, request_id, now)
    else:
        _record(session, "crm.no_channel", request_id)
        logger.error("crm.no_channel: уведомление не доставлено; проверьте канал клиники")


def _deliver_one(session: Session, row: Outbox, now: datetime, send: Send) -> None:
    try:
        request_id = json.loads(row.payload)["request_id"]
        if not isinstance(request_id, str):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        row.status, row.processed_at = "failed", now
        logger.error("crm.invalid_task: проверьте запись очереди")
        return
    request = session.scalar(select(Request).where(Request.id == request_id)
                             .with_for_update().execution_options(populate_existing=True))
    if request is None:
        row.status, row.processed_at = "failed", now
        return
    patient = session.get(Patient, request.patient_id, populate_existing=True)
    if patient is None:
        row.status, row.processed_at = "failed", now
        return
    if patient.opted_out:
        if request.status not in {"booked", "cancelled"}:
            request.status = "cancelled"
        row.status, row.processed_at = "done", now
        _record(session, "crm.skipped_opted_out", request.id)
        return
    if request.status in {"booked", "cancelled"}:
        row.status, row.processed_at = "done", now
        return
    settings = get_settings()
    target = (settings.crm_targets if row.topic == "crm" else settings.notify_targets).get(
        patient.clinic_id)
    if target is None:
        if row.topic == "crm":
            row.status, row.processed_at = "done", now
            _notify(session, request.id, now)
        else:
            row.status, row.processed_at = "failed", now
            _record(session, "crm.no_channel", request.id)
            logger.error("crm.no_channel: канал клиники не настроен; задайте NOTIFY_TARGETS")
        return
    try:
        clinic = session.get(Clinic, patient.clinic_id)
        if clinic is None:
            raise DeliveryError()
        payload = _payload(session, request, patient, clinic)
        kind = target["kind"] if row.topic == "crm" else "notify"
        reason = None
        if row.topic == "notify":
            payload.pop("patient_token")
            payload.pop("created_at")
            failed = session.scalar(select(AuditEvent.id).where(
                AuditEvent.action == "crm.request_failed", AuditEvent.entity_id == request.id,
            ).limit(1))
            reason = "crm_failed" if failed else "no_crm"
            payload["reason"] = reason
        crm_id = send(kind, target, payload)
    except Exception:
        # Не логируем исключение: в нём могут быть телефон и секретный URL.
        _failed(session, row, request.id, now)
        return
    row.status, row.processed_at = "done", now
    if row.topic == "notify":
        # Уведомление администратору — не отправка в CRM: статус заявки не меняется.
        audit.record(session, action="crm.notify_sent", actor_id="system", entity="request",
                     entity_id=request.id, payload={"reason": reason})
        return
    if crm_id is not None:
        request.crm_request_id = crm_id
    if request.status == "new":
        request.status = "sent"
    _record(session, "crm.request_sent", request.id)


def deliver_pending(session: Session, now: datetime, send: Send = http_send) -> int:
    """Обрабатывает готовые crm/notify; вызывающий делает commit.

    Условный UPDATE удерживает блокировку до commit, включая HTTP-запрос.
    Исключения процесса требуют rollback; повтор после неопределённого ответа
    сети может дублировать внешнюю заявку (см. ограничение в контракте).
    """
    now = _utc(now)
    count = 0
    while True:
        ready = (
            Outbox.topic.in_(("crm", "notify")), Outbox.status == "pending",
            or_(Outbox.available_at.is_(None), Outbox.available_at <= now),
        )
        ids = list(session.scalars(select(Outbox.id).where(*ready).order_by(
            Outbox.created_at, Outbox.id)))
        if not ids:
            break
        claimed = 0
        for row_id in ids:
            row = session.scalar(update(Outbox).where(Outbox.id == row_id, *ready)
                                 .values(status="processing").returning(Outbox)
                                 .execution_options(populate_existing=True))
            if row is None:
                continue
            claimed += 1
            count += 1
            _deliver_one(session, row, now, send)
            session.flush()
        if not claimed:
            break
    return count


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message})


def change_status(
    session: Session, status: str, *, request_id: str | None = None,
    crm_request_id: str | None = None, actor_id: str, manual: bool = False,
) -> StatusResult:
    query = select(Request)
    if request_id is not None:
        query = query.where(Request.id == request_id)
    else:
        query = query.where(Request.crm_request_id == crm_request_id)
    if manual:
        query = query.join(Patient, Patient.id == Request.patient_id).where(
            Patient.clinic_id == get_settings().mis_clinic_id)
    # Внешние ID не уникальны в схеме B1: неоднозначный ID не выбираем наугад.
    requests = list(session.scalars(query.with_for_update(of=Request)
                                   .execution_options(populate_existing=True)))
    if len(requests) != 1:
        raise _error(404, "request_not_found", "Заявка не найдена. Проверьте идентификатор.")
    request = requests[0]
    old = request.status
    if old == status:
        session.commit()
        return StatusResult(request_id=request.id, status=status)
    if status not in TRANSITIONS.get(old, set()):
        session.rollback()
        raise _error(409, "invalid_transition",
                     "Статус уже изменён. Обновите заявку и проверьте переход.")
    changed = session.scalar(update(Request).where(Request.id == request.id, Request.status == old)
                             .values(status=status).returning(Request.id))
    if changed is None:
        session.rollback()
        raise _error(409, "invalid_transition",
                     "Статус уже изменён. Обновите заявку и повторите запрос.")
    audit.record(session, action="crm.status_changed", actor_id=actor_id,
                 role="administrator" if manual else "crm", entity="request", entity_id=request.id,
                 payload={"from": old, "to": status})
    session.commit()
    return StatusResult(request_id=request.id, status=status)
