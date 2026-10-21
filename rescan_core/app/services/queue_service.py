"""Очередь врача (B4).

Основная группа после приёма события ждёт отметки своего врача 24 часа.
Врач отмечает шаг по одному эпизоду; без отметки эпизод уходит в
стандартное сообщение. Время всегда передаётся параметром и хранится в UTC.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from fastapi import HTTPException, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.db.models import Clinic, Doctor, Outbox, Step
from app.repositories.queue_repository import QueueRepository
from app.schemas.queue import (
    QueueItem,
    QueueResponse,
    StepCode,
    StepMarkRequest,
    StepMarkResult,
    StepOption,
    StepOptionsResponse,
)
from app.services import audit

QUEUE_WINDOW = timedelta(hours=24)
SYSTEM_ACTOR = "system"
NOT_CONFIGURED = "Список шагов клиники не настроен."

_OPTIONS = TypeAdapter(list[StepOption])


class EpisodeStatus(StrEnum):
    AWAITING_DOCTOR = "awaiting_doctor"
    CONTROL = "control"
    DOCTOR_MARKED = "doctor_marked"
    DEFAULT_MESSAGE = "default_message"


def as_utc(value: datetime) -> datetime:
    """Время без пояса считаем UTC (так его возвращает SQLite)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def queue_deadline(received_at: datetime) -> datetime:
    """Срок отметки — от времени приёма события, а не от ready_at."""
    return as_utc(received_at) + QUEUE_WINDOW


def parse_step_options(raw: str | None) -> list[StepOption]:
    """Пустые или испорченные настройки — 503, без значений по умолчанию."""
    try:
        options = _OPTIONS.validate_python(json.loads(raw or "null"))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED) from exc
    codes = [option.code for option in options]
    if not options or len(set(codes)) != len(codes):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)
    return options


def _outbox(session: Session, topic: str, payload: dict, now: datetime) -> None:
    session.add(Outbox(topic=topic, payload=json.dumps(payload), available_at=now))


@dataclass(frozen=True)
class DoctorContext:
    clinic: Clinic
    doctor: Doctor
    options: list[StepOption]


class QueueService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = QueueRepository(session)

    def doctor_context(self, actor_id: str) -> DoctorContext:
        clinic = self.repo.integration_clinic()
        if clinic is None:
            raise HTTPException(503, "Клиника интеграции не настроена. Проверьте MIS_CLINIC_ID.")
        doctor = self.repo.find_doctor(clinic.id, actor_id)
        if doctor is None:
            raise HTTPException(403, "Врач не найден в клинике. Обратитесь к администратору.")
        if not clinic.service_enabled:
            raise HTTPException(403, "Сервис для клиники остановлен.")
        return DoctorContext(clinic, doctor, parse_step_options(clinic.step_options))

    def queue(self, actor_id: str, *, now: datetime) -> QueueResponse:
        now = as_utc(now)
        context = self.doctor_context(actor_id)
        items = [
            QueueItem(
                episode_id=row[0], patient_token=row[1], branch_name=row[2],
                ready_at=as_utc(row[3]), queue_deadline_at=as_utc(row[4]),
            )
            for row in self.repo.list_queue(context.doctor.id, now)
        ]
        return QueueResponse(server_time=now, items=items)

    def step_options(self, actor_id: str) -> StepOptionsResponse:
        return StepOptionsResponse(options=self.doctor_context(actor_id).options)

    def mark_step(self, actor_id: str, episode_id: str, request: StepMarkRequest,
                  *, now: datetime) -> StepMarkResult:
        now = as_utc(now)
        context = self.doctor_context(actor_id)
        _check_choice(context.options, request)

        if self.repo.get_doctor_episode(episode_id, context.doctor.id) is None:
            raise HTTPException(404, "Эпизод не найден.")
        if not self.repo.claim_for_mark(episode_id, now, EpisodeStatus.DOCTOR_MARKED.value):
            self.session.rollback()
            raise HTTPException(409, "Шаг уже отмечен или срок отметки прошёл.")

        due_date = None
        if request.code is StepCode.RETEST and request.retest_weeks is not None:
            due_date = now + timedelta(weeks=request.retest_weeks)
        step = Step(episode_id=episode_id, kind=request.code.value, due_date=due_date,
                    set_by_doctor_id=context.doctor.id, set_at=now)
        self.session.add(step)
        self.session.flush()

        details = {"step_id": step.id, "code": request.code.value,
                   "retest_weeks": request.retest_weeks}
        audit.record(self.session, action="doctor.step_marked", actor_id=actor_id,
                     role="doctor", entity="episode", entity_id=episode_id, payload=details)
        _outbox(self.session, "episode.doctor_marked", {"episode_id": episode_id, **details}, now)
        self.session.commit()
        return StepMarkResult(episode_id=episode_id, step_id=step.id,
                              status=EpisodeStatus.DOCTOR_MARKED.value)


def _check_choice(options: list[StepOption], request: StepMarkRequest) -> None:
    """Код включён в клинике, недели — только для retest и только из списка."""
    option = next((item for item in options if item.code is request.code), None)
    if option is None:
        raise HTTPException(422, "Этот шаг в клинике выключен.")
    if request.code is StepCode.RETEST:
        if request.retest_weeks not in (option.weeks or []):
            raise HTTPException(422, "Выберите срок пересдачи из списка клиники.")
    elif "retest_weeks" in request.model_fields_set:
        raise HTTPException(422, "Срок пересдачи передаётся только для retest.")


def expire_overdue(session: Session, now: datetime) -> int:
    """Эпизоды без отметки со сроком <= now → default_message. Повтор ничего не меняет."""
    now = as_utc(now)
    repo = QueueRepository(session)
    expired = 0
    for episode_id in repo.overdue_ids(now):
        if not repo.claim_overdue(episode_id, now, EpisodeStatus.DEFAULT_MESSAGE.value):
            continue  # врач успел отметить или другой запуск уже перевёл
        audit.record(session, action="queue.expired", actor_id=SYSTEM_ACTOR, role=SYSTEM_ACTOR,
                     entity="episode", entity_id=episode_id)
        _outbox(session, "episode.default_message", {"episode_id": episode_id}, now)
        expired += 1
    session.commit()
    return expired
