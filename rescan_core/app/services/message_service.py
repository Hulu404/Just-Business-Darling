"""B5: Очередь уведомлений (Telegram/SMS), тихие часы и ретраи."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Consent, Contact, Episode, Outbox, Patient
from app.security.crypto import decrypt_phone
from app.security.patient_link import new_token, hash_token
from app.services import audit
from app.services.notification_transports import DeliveryError, send_notification

SendNotification = Callable[[str, str, str | None], None]
RETRY_MINUTES = (3 * 24 * 60,)  # Один повтор через 3 дня
QUIET_START_HOUR = 21
QUIET_END_HOUR = 9
PATIENT_PAGE = "/assets/pilot/index.html#/p/"

logger = logging.getLogger(__name__)

def _utc(now: datetime) -> datetime:
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)

def _in_quiet_hours(now: datetime) -> bool:
    return now.hour >= QUIET_START_HOUR or now.hour < QUIET_END_HOUR

def _next_morning(now: datetime) -> datetime:
    target = now.replace(hour=QUIET_END_HOUR, minute=0, second=0, microsecond=0)
    if now.hour >= QUIET_START_HOUR:
        target += timedelta(days=1)
    return target

def _failed(row: Outbox, now: datetime) -> None:
    row.attempts += 1
    if row.attempts <= len(RETRY_MINUTES):
        row.status = "pending"
        row.available_at = now + timedelta(minutes=RETRY_MINUTES[row.attempts - 1])
    else:
        row.status = "failed"
        row.processed_at = now
        logger.error("Уведомление не доставлено после всех попыток.")

def _build_text(session: Session, patient_id: str, link: str, template: str) -> str:
    consent = session.execute(
        select(Consent).where(Consent.patient_id == patient_id,
                              Consent.kind == "marketing",
                              Consent.granted.is_(True))
    ).scalar_one_or_none()

    if template == "doctor_marked":
        base = "Ваш врач оставил для вас рекомендацию. "
    else:
        base = "Ваши анализы готовы. "

    if consent:
        base += "Перейдите по ссылке, чтобы записаться к врачу клиники: "
    else:
        base += "Информация о дальнейших шагах доступна по ссылке: "

    return base + link

def _issue_link(session: Session, episode_id: str, now: datetime) -> str:
    from app.db.models import PatientLink
    settings = get_settings()
    token = new_token()
    ttl = timedelta(days=settings.patient_link_ttl_days)
    session.add(PatientLink(episode_id=episode_id, token_hash=hash_token(token),
                            expires_at=now + ttl, created_at=now))
    session.flush()
    return f"https://example-clinic.ru{PATIENT_PAGE}{token}"

def deliver_pending_messages(session: Session, now: datetime, send: SendNotification = send_notification) -> int:
    now = _utc(now)
    count = 0

    while True:
        ready = (
            Outbox.topic == "notification",  # Меняем topic с sms на notification
            Outbox.status == "pending",
            or_(Outbox.available_at.is_(None), Outbox.available_at <= now),
        )
        ids = list(session.scalars(select(Outbox.id).where(*ready).order_by(Outbox.created_at)))
        if not ids:
            break

        claimed = 0
        for row_id in ids:
            row = session.scalar(
                update(Outbox).where(Outbox.id == row_id, *ready)
                .values(status="processing")
                .returning(Outbox)
                .execution_options(populate_existing=True, synchronize_session=False)
            )
            if row is None:
                continue
            claimed += 1
            count += 1

            try:
                payload = json.loads(row.payload)
                episode_id = payload["episode_id"]
                template = payload.get("template", "default")

                if _in_quiet_hours(now):
                    row.status = "pending"
                    row.available_at = _next_morning(now)
                    session.flush()
                    continue

                episode = session.get(Episode, episode_id)
                if not episode:
                    row.status, row.processed_at = "failed", now
                    session.flush()
                    continue

                if episode.group != "main":
                    row.status, row.processed_at = "done", now
                    audit.record(session, action="message.skipped_control", entity="episode", entity_id=episode_id)
                    session.flush()
                    continue

                patient = session.get(Patient, episode.patient_id)
                if not patient or patient.opted_out:
                    row.status, row.processed_at = "done", now
                    audit.record(session, action="message.skipped_opted_out", entity="episode", entity_id=episode_id)
                    session.flush()
                    continue

                contact = session.scalar(
                    select(Contact).where(Contact.patient_id == patient.id).limit(1)
                )
                if not contact:
                    row.status, row.processed_at = "failed", now
                    session.flush()
                    continue

                link = _issue_link(session, episode_id, now)
                phone = decrypt_phone(contact.phone_enc)
                text = _build_text(session, patient.id, link, template)

                # ПЕРЕДАЕМ telegram_id (если есть)!
                send(phone, text, contact.telegram_id)

                row.status = "done"
                row.processed_at = now
                audit.record(session, action="message.sent", entity="episode", entity_id=episode_id)

            except Exception:
                _failed(row, now)

            session.flush()
        if not claimed:
            break

    return count