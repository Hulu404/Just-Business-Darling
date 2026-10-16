"""Приём событий МИС (B2) поверх готовой БД (B1).

Полный контур: событие → справочники → пациент → контакт → эпизод → группа.
Идемпотентность — по UNIQUE(event_id).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Episode, Event
from app.repositories.event_repository import (
    ClinicRepository,
    DirectoryRepository,
    EventRepository,
    PatientRepository,
)
from app.schemas.events import IngestResult, IngestStatus, ResultsReadyEvent
from app.services import audit
from app.services.group_service import Group, assign_group


class IngestService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.events = EventRepository(session)
        self.directory = DirectoryRepository(session)
        self.patients = PatientRepository(session)
        self.clinics = ClinicRepository(session)

    def ingest(self, event: ResultsReadyEvent, *, raw: bytes | None = None,
               actor_id: str | None = None) -> IngestResult:
        # 1) Быстрая проверка дубля (не создаём второй эпизод).
        existing = self.events.get_event(event.event_id)
        if existing is not None:
            return IngestResult(
                status=IngestStatus.DUPLICATE,
                event_id=event.event_id,
                episode_id=existing.episode_id,
                group=None,
            )

        clinic = self.clinics.first_clinic()
        if clinic is None:
            raise RuntimeError(
                "в базе нет ни одной клиники — сначала загрузите демо-данные "
                "(python -m scripts.seed_demo)"
            )

        # 2) Справочники.
        branch = self.directory.get_or_create_branch(clinic.id, event.branch_id)
        doctor = self.directory.get_or_create_doctor(clinic.id, event.ordering_doctor_id)

        # 3) Пациент и защищённый контакт.
        patient = self.patients.get_or_create_patient(clinic.id, event.patient_token)
        self.patients.upsert_contact(patient.id, event.phone)

        # 4) Группа фиксируется один раз и не меняется (B3).
        if patient.group is None:
            patient.group = assign_group(event.patient_token).value
        group_value = Group(patient.group)

        # 5) Эпизод.
        episode = Episode(
            patient_id=patient.id,
            branch_id=branch.id,
            ordering_doctor_id=doctor.id,
            group=group_value.value,
            status="open",
            ready_at=event.ready_at,
        )
        self.session.add(episode)
        self.session.flush()

        # 6) Само событие (для идемпотентности и разбора инцидентов).
        stored = Event(
            event_id=event.event_id,
            clinic_id=clinic.id,
            branch_external_id=event.branch_id,
            patient_token=event.patient_token,
            ordering_doctor_external_id=event.ordering_doctor_id,
            ready_at=event.ready_at,
            marketing_consent=event.marketing_consent,
            episode_id=episode.id,
            raw_payload=raw.decode() if raw else None,
        )
        inserted = self.events.add_event(stored)
        if not inserted:
            # Гонка: параллельный запрос успел вставить то же событие.
            self.session.rollback()
            return IngestResult(status=IngestStatus.DUPLICATE, event_id=event.event_id)

        # 7) Согласие (B11): фиксируем наличие согласия на рекламу.
        from app.db.models import Consent

        self.session.add(
            Consent(patient_id=patient.id, kind="marketing",
                    granted=event.marketing_consent, source="mis")
        )

        # 8) Аудит — без ПДн.
        audit.record(
            self.session,
            action="mis.event.accepted",
            actor_id=actor_id or "mis",
            role="mis",
            entity="event",
            entity_id=event.event_id,
            payload={"episode_id": episode.id, "group": group_value.value},
        )

        self.session.commit()
        return IngestResult(
            status=IngestStatus.CREATED,
            event_id=event.event_id,
            episode_id=episode.id,
            group=group_value.value,
        )
