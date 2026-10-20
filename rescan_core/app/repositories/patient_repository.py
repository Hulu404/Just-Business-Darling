"""Запросы API пациента (B6)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    Clinic,
    Consent,
    Doctor,
    Episode,
    Format,
    Goal,
    GoalDoctor,
    PatientLink,
    Request,
    Step,
    Visit,
)

PD_PROCESSING = "pd_processing"
OPEN_REQUEST_STATUSES = ("new", "sent", "in_progress")


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- ссылка и эпизод ---

    def find_link(self, token_hash: str) -> PatientLink | None:
        return self.session.execute(
            select(PatientLink).where(PatientLink.token_hash == token_hash)
        ).scalar_one_or_none()

    def get_episode(self, episode_id: str) -> Episode | None:
        return self.session.get(Episode, episode_id)

    def get_clinic(self, clinic_id: str) -> Clinic | None:
        return self.session.get(Clinic, clinic_id)

    def lock_episode(self, episode_id: str, now: datetime) -> None:
        """Условный UPDATE строки эпизода: заявки одного эпизода создаются по очереди."""
        self.session.execute(
            update(Episode).where(Episode.id == episode_id).values(updated_at=now)
            .execution_options(synchronize_session=False)
        )

    # --- шаг врача и согласие ---

    def latest_doctor_step(self, episode_id: str) -> tuple[Step, str | None] | None:
        row = self.session.execute(
            select(Step, Doctor.full_name)
            .join(Doctor, Doctor.id == Step.set_by_doctor_id)
            .where(Step.episode_id == episode_id, Step.set_by_doctor_id.is_not(None))
            .order_by(Step.set_at.desc(), Step.created_at.desc(), Step.id.desc())
            .limit(1)
        ).first()
        return None if row is None else (row[0], row[1])

    def has_consent(self, patient_id: str) -> bool:
        return self.session.execute(
            select(Consent.id).where(
                Consent.patient_id == patient_id,
                Consent.kind == PD_PROCESSING,
                Consent.granted.is_(True),
            ).limit(1)
        ).first() is not None

    # --- цели, врачи, форматы ---

    def active_goals(self, clinic_id: str) -> list[Goal]:
        return list(self.session.execute(
            select(Goal).where(Goal.clinic_id == clinic_id, Goal.is_active.is_(True))
            .order_by(Goal.sort_order, Goal.title, Goal.id)
        ).scalars())

    def active_doctor(self, clinic_id: str, doctor_id: str | None) -> Doctor | None:
        if doctor_id is None:
            return None
        return self.session.execute(
            select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == clinic_id,
                                 Doctor.is_active.is_(True))
        ).scalar_one_or_none()

    def goal_doctors(self, clinic_id: str, goal_id: str) -> list[tuple[Doctor, int]]:
        """Активные врачи цели этой клиники с порядком клиники."""
        rows = self.session.execute(
            select(Doctor, GoalDoctor.sort_order)
            .join(GoalDoctor, GoalDoctor.doctor_id == Doctor.id)
            .where(GoalDoctor.goal_id == goal_id, Doctor.clinic_id == clinic_id,
                   Doctor.is_active.is_(True))
            .order_by(GoalDoctor.sort_order, Doctor.id)
        ).all()
        return [(row[0], row[1]) for row in rows]

    def last_visits(self, clinic_id: str, patient_token: str) -> dict[str, datetime]:
        """Последний визит пациента к каждому врачу клиники (по external_id врача)."""
        rows = self.session.execute(
            select(Visit.doctor_external_id, func.max(Visit.visit_date))
            .where(Visit.clinic_id == clinic_id, Visit.patient_token == patient_token,
                   Visit.doctor_external_id.is_not(None))
            .group_by(Visit.doctor_external_id)
        ).all()
        return {row[0]: row[1] for row in rows}

    def active_formats(self, clinic_id: str) -> list[Format]:
        return list(self.session.execute(
            select(Format).where(Format.clinic_id == clinic_id, Format.is_active.is_(True))
            .order_by(Format.created_at, Format.title, Format.id)
        ).scalars())

    def active_format(self, clinic_id: str, format_id: str) -> Format | None:
        return self.session.execute(
            select(Format).where(Format.id == format_id, Format.clinic_id == clinic_id,
                                 Format.is_active.is_(True))
        ).scalar_one_or_none()

    # --- заявки ---

    def latest_request(self, episode_id: str) -> Request | None:
        """Последняя незавершённая заявка, иначе последняя завершённая."""
        for open_only in (True, False):
            query = select(Request).where(Request.episode_id == episode_id)
            if open_only:
                query = query.where(Request.status.in_(OPEN_REQUEST_STATUSES))
            found = self.session.execute(
                query.order_by(Request.created_at.desc(), Request.id.desc()).limit(1)
            ).scalar_one_or_none()
            if found is not None:
                return found
        return None

    def has_open_request(self, episode_id: str) -> bool:
        return self.session.execute(
            select(Request.id).where(Request.episode_id == episode_id,
                                     Request.status.in_(OPEN_REQUEST_STATUSES)).limit(1)
        ).first() is not None

    def doctor_name(self, doctor_id: str | None) -> str | None:
        doctor = self.session.get(Doctor, doctor_id) if doctor_id else None
        return doctor.full_name if doctor else None

    def format_title(self, format_id: str | None) -> str | None:
        found = self.session.get(Format, format_id) if format_id else None
        return found.title if found else None
