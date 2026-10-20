"""Запросы очереди врача (B4).

Переходы статуса эпизода — только условным UPDATE по текущему статусу:
две конкурентные операции над одним эпизодом дают ровно один результат.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Row, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Branch, Clinic, Doctor, Episode, Patient

AWAITING_DOCTOR = "awaiting_doctor"


class QueueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def integration_clinic(self) -> Clinic | None:
        """Та же клиника, что принимает события МИС; стоп-кнопку проверяет сервис."""
        settings = get_settings()
        if settings.mis_clinic_id:
            return self.session.get(Clinic, settings.mis_clinic_id)
        if settings.environment in {"local", "test"}:
            clinics = self.session.execute(select(Clinic).limit(2)).scalars().all()
            return clinics[0] if len(clinics) == 1 else None
        return None

    def find_doctor(self, clinic_id: str, external_id: str) -> Doctor | None:
        return self.session.execute(
            select(Doctor).where(
                Doctor.clinic_id == clinic_id,
                Doctor.external_id == external_id,
                Doctor.is_active.is_(True),
            )
        ).scalar_one_or_none()

    def list_queue(self, doctor_id: str, now: datetime) -> list[Row]:
        """Эпизоды врача, ждущие отметки, со сроком в будущем, без отписавшихся."""
        return list(self.session.execute(
            select(
                Episode.id, Patient.patient_token, Branch.name,
                Episode.ready_at, Episode.queue_deadline_at,
            )
            .join(Patient, Patient.id == Episode.patient_id)
            .outerjoin(Branch, Branch.id == Episode.branch_id)
            .where(
                Episode.ordering_doctor_id == doctor_id,
                Episode.status == AWAITING_DOCTOR,
                Episode.queue_deadline_at > now,
                Patient.opted_out.is_(False),
            )
            .order_by(Episode.queue_deadline_at, Episode.id)
        ).all())

    def get_doctor_episode(self, episode_id: str, doctor_id: str) -> Episode | None:
        """Эпизод основной группы этого врача; чужой и контрольный не отличаем от отсутствующего."""
        return self.session.execute(
            select(Episode)
            .join(Patient, Patient.id == Episode.patient_id)
            .where(
                Episode.id == episode_id,
                Episode.ordering_doctor_id == doctor_id,
                Episode.group == "main",
                Patient.opted_out.is_(False),
            )
        ).scalar_one_or_none()

    def claim_for_mark(self, episode_id: str, now: datetime, new_status: str) -> bool:
        """Перевести эпизод из ожидания, пока срок не прошёл. False — уже не ждёт."""
        result = self.session.execute(
            update(Episode)
            .where(
                Episode.id == episode_id,
                Episode.status == AWAITING_DOCTOR,
                Episode.queue_deadline_at > now,
            )
            .values(status=new_status, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def overdue_ids(self, now: datetime) -> list[str]:
        return list(self.session.execute(
            select(Episode.id)
            .where(Episode.status == AWAITING_DOCTOR, Episode.queue_deadline_at <= now)
            .order_by(Episode.queue_deadline_at, Episode.id)
        ).scalars())

    def claim_overdue(self, episode_id: str, now: datetime, new_status: str) -> bool:
        result = self.session.execute(
            update(Episode)
            .where(
                Episode.id == episode_id,
                Episode.status == AWAITING_DOCTOR,
                Episode.queue_deadline_at <= now,
            )
            .values(status=new_status, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]
