"""Репозиторий событий и связанных сущностей (SQLAlchemy).

Идемпотентность B2 опирается на UNIQUE(event_id) в таблице events: вставку
делаем «вслепую», а на конфликт реагируем. Это надёжнее, чем «SELECT, потом
INSERT», где между двумя запросами успевает проскочить второй вебхук.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Branch, Clinic, Contact, Doctor, Event, Patient
from app.security.crypto import encrypt_phone, hash_phone


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_event(self, event_id: str) -> Event | None:
        return self.session.execute(
            select(Event).where(Event.event_id == event_id)
        ).scalar_one_or_none()

    def add_event(self, event: Event) -> bool:
        """Вставить событие. False — если такое event_id уже есть (дубль).

        Ловим IntegrityError по уникальному индексу: это и есть защита от гонки
        двух одинаковых вебхуков, пришедших почти одновременно.
        """
        self.session.add(event)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            return False
        return True


class DirectoryRepository:
    """Справочники: клиники, филиалы, врачи. Upsert по внешним id из МИС."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_branch(self, clinic_id: str, external_id: str) -> Branch:
        branch = self.session.execute(
            select(Branch).where(
                Branch.clinic_id == clinic_id, Branch.external_id == external_id
            )
        ).scalar_one_or_none()
        if branch is None:
            branch = Branch(clinic_id=clinic_id, external_id=external_id)
            self.session.add(branch)
            self.session.flush()
        return branch

    def get_or_create_doctor(self, clinic_id: str, external_id: str) -> Doctor:
        doctor = self.session.execute(
            select(Doctor).where(
                Doctor.clinic_id == clinic_id, Doctor.external_id == external_id
            )
        ).scalar_one_or_none()
        if doctor is None:
            doctor = Doctor(clinic_id=clinic_id, external_id=external_id,
                            full_name=f"Врач {external_id}")
            self.session.add(doctor)
            self.session.flush()
        return doctor


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_patient(self, clinic_id: str, patient_token: str) -> Patient:
        patient = self.session.execute(
            select(Patient).where(
                Patient.clinic_id == clinic_id, Patient.patient_token == patient_token
            )
        ).scalar_one_or_none()
        if patient is None:
            patient = Patient(clinic_id=clinic_id, patient_token=patient_token)
            self.session.add(patient)
            self.session.flush()
        return patient

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

    def first_clinic(self) -> Clinic | None:
        """Демо-хелпер: пилотная клиника одна, берём первую активную."""
        return self.session.execute(select(Clinic).limit(1)).scalar_one_or_none()
