"""Репозиторий событий и связанных сущностей (SQLAlchemy).

Идемпотентность B2 опирается на UNIQUE(event_id) в таблице events: вставку
делаем «вслепую», а на конфликт реагируем. Это надёжнее, чем «SELECT, потом
INSERT», где между двумя запросами успевает проскочить второй вебхук.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Branch, Clinic, Contact, Doctor, Event, Patient
from app.db.upsert import insert_unique
from app.security.crypto import encrypt_phone, hash_phone


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_event(self, event_id: str) -> Event | None:
        return self.session.execute(
            select(Event).where(Event.event_id == event_id)
        ).scalar_one_or_none()

    def claim_event(self, event_id: str, **values) -> tuple[Event, bool]:
        """Занять event_id до создания связанных объектов в той же транзакции."""
        return insert_unique(self.session, Event, {"event_id": event_id}, **values)


class DirectoryRepository:
    """Справочники: клиники, филиалы, врачи. Upsert по внешним id из МИС."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_branch(self, clinic_id: str, external_id: str) -> Branch:
        branch, _ = insert_unique(
            self.session, Branch, {"clinic_id": clinic_id, "external_id": external_id},
        )
        return branch

    def get_or_create_doctor(self, clinic_id: str, external_id: str) -> Doctor:
        doctor, _ = insert_unique(
            self.session, Doctor, {"clinic_id": clinic_id, "external_id": external_id},
            full_name=f"Врач {external_id}",
        )
        return doctor


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_patient(self, clinic_id: str, patient_token: str) -> Patient:
        patient, _ = insert_unique(
            self.session, Patient, {"clinic_id": clinic_id, "patient_token": patient_token},
        )
        # В PostgreSQL сериализуем контакт и первичное назначение группы пациента.
        # В SQLite запись события уже удерживает блокировку записи транзакции.
        return self.session.execute(
            select(Patient).where(Patient.id == patient.id).with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()

    def upsert_contact(self, patient_id: str, phone: str) -> Contact:
        """Телефон хранится зашифрованным; ищем по хэшу, не по открытому номеру."""
        phone_hash = hash_phone(phone)
        contact = self.session.execute(
            select(Contact).where(
                Contact.patient_id == patient_id, Contact.phone_hash == phone_hash
            )
        ).scalar_one_or_none()
        if contact is None:
            contact = Contact(
                patient_id=patient_id,
                channel="sms",
                phone_enc=encrypt_phone(phone),
                phone_hash=phone_hash,
            )
            self.session.add(contact)
            self.session.flush()
        return contact


class ClinicRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_clinic(self, clinic_id: str) -> Clinic | None:
        return self.session.get(Clinic, clinic_id)

    def integration_clinic(self) -> Clinic:
        """В проде клиника задана явно; локально допускается ровно одна клиника."""
        settings = get_settings()
        if settings.mis_clinic_id:
            clinic = self.get_clinic(settings.mis_clinic_id)
        elif settings.environment in {"local", "test"}:
            clinics = self.session.execute(select(Clinic).limit(2)).scalars().all()
            clinic = clinics[0] if len(clinics) == 1 else None
        else:
            clinic = None
        if clinic is None:
            raise HTTPException(503, "Клиника интеграции не настроена. Проверьте MIS_CLINIC_ID.")
        if not clinic.service_enabled:
            raise HTTPException(403, "Приём событий для клиники выключен.")
        return clinic
