"""Модели БД (B1). Все 16 таблиц из дорожной карты:

clinics, branches, doctors, formats, goals, patients, contacts, episodes,
steps, messages, requests, visits, consents, events, audit_events, outbox.

Правило проекта: персональные данные (телефон) живут ТОЛЬКО в contacts и
только в зашифрованном виде. Поля о здоровье (результаты, диагнозы) здесь
отсутствуют по определению — см. «Чего в бэкенде нет».
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin, utcnow


class Clinic(IdMixin, TimestampMixin, Base):
    """Клиника (тенант). В проде — пилотная клиника и её филиалы."""

    __tablename__ = "clinics"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Токены темы оформления (лого, акцент, название) — отдаются фронтенду.
    theme: Mapped[str | None] = mapped_column(Text)  # JSON-строка с токенами
    # Стоп-кнопка клиники: если false, сервис для клиники выключен целиком.
    service_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Шаги врача, включённые клиникой (B4): JSON-список {code, title, weeks?}.
    step_options: Mapped[str | None] = mapped_column(Text)
    # Настройки страницы пациента (B6): JSON-строка с телефоном, ветками, окнами и текстами.
    patient_settings: Mapped[str | None] = mapped_column(Text)


class Branch(IdMixin, TimestampMixin, Base):
    """Филиал клиники."""

    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("clinic_id", "external_id", name="uq_branch_ext"),)

    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)  # id филиала в МИС
    name: Mapped[str | None] = mapped_column(String(255))


class Doctor(IdMixin, TimestampMixin, Base):
    """Врач. Специальность, порядок показа и привязка к клинике."""

    __tablename__ = "doctors"
    __table_args__ = (UniqueConstraint("clinic_id", "external_id", name="uq_doctor_ext"),)

    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)  # id врача в МИС
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Format(IdMixin, TimestampMixin, Base):
    """Формат приёма (очный, телемедицина) и цена."""

    __tablename__ = "formats"

    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    price_kopecks: Mapped[int | None] = mapped_column(Integer)  # деньги целым числом
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    payment_url: Mapped[str | None] = mapped_column(String(512))  # ссылка на оплату клиники
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Goal(IdMixin, TimestampMixin, Base):
    """Цель визита (нейтральные формулировки из настроек клиники)."""

    __tablename__ = "goals"

    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Patient(IdMixin, TimestampMixin, Base):
    """Пациент в обезличенном виде. Ключ сверки — patient_token из МИС."""

    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("clinic_id", "patient_token", name="uq_patient_token"),)

    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    patient_token: Mapped[str] = mapped_column(String(128), nullable=False)
    # Группа фиксируется один раз при первом событии (B3). Дублируем на пациенте
    # и на эпизоде: на пациенте — «истина», на эпизоде — снимок.
    group: Mapped[str | None] = mapped_column(String(16))  # main | control
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Contact(IdMixin, TimestampMixin, Base):
    """Контакт пациента. Телефон хранится ТОЛЬКО здесь и ТОЛЬКО зашифрованным.

    phone_enc — шифротекст (Fernet). phone_hash — детерминированный хэш для
    поиска/дедупа без доступа к открытому номеру.
    """

    __tablename__ = "contacts"

    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), default="sms")
    phone_enc: Mapped[str] = mapped_column(Text, nullable=False)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    telegram_id: Mapped[str | None] = mapped_column(String(64))

class Episode(IdMixin, TimestampMixin, Base):
    """Эпизод — один проход пациента по маршруту после готовности анализов."""

    __tablename__ = "episodes"

    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"))
    ordering_doctor_id: Mapped[str | None] = mapped_column(ForeignKey("doctors.id"))
    # Группа-снимок на момент эпизода (может отличаться от Patient.group, если
    # правила поменяют; для пилота совпадает).
    group: Mapped[str] = mapped_column(String(16), nullable=False)  # main | control
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    ready_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Срок отметки врача (B4): время приёма события + 24 часа, только основная группа.
    queue_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Выбор пациента по ссылке (B6): ветка, если врач не отметил шаг, и цель визита.
    chosen_branch: Mapped[str | None] = mapped_column(String(16))
    chosen_goal_id: Mapped[str | None] = mapped_column(
        ForeignKey("goals.id", name="fk_episodes_chosen_goal_id"))


class Step(IdMixin, TimestampMixin, Base):
    """Шаг маршрута, назначенный врачом (наблюдение, пересдача, приём и т.д.).

    Статусы: open → offered → confirmed → attended → completed.
    """

    __tablename__ = "steps"

    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # из фикс. списка
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    set_by_doctor_id: Mapped[str | None] = mapped_column(ForeignKey("doctors.id"))
    set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(IdMixin, TimestampMixin, Base):
    """Исходящее сообщение (SMS/письмо) и его состояние."""

    __tablename__ = "messages"

    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(128))


class Request(IdMixin, TimestampMixin, Base):
    """Заявка пациента. Живёт здесь и уходит вебхуком в CRM клиники."""

    __tablename__ = "requests"

    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    doctor_id: Mapped[str | None] = mapped_column(ForeignKey("doctors.id"))
    format_id: Mapped[str | None] = mapped_column(ForeignKey("formats.id"))
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("goals.id"))
    window: Mapped[str | None] = mapped_column(String(64))  # удобное окно времени
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False)
    crm_request_id: Mapped[str | None] = mapped_column(String(128))


class Visit(IdMixin, TimestampMixin, Base):
    """Визит из выгрузки МИС. Ключ сверки — patient_token."""

    __tablename__ = "visits"
    __table_args__ = (UniqueConstraint("clinic_id", "external_id", name="uq_visit_ext"),)

    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))  # id визита в МИС, если есть
    patient_token: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    visit_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_kopecks: Mapped[int] = mapped_column(Numeric(14, 2), default=0)
    doctor_external_id: Mapped[str | None] = mapped_column(String(64))
    branch_external_id: Mapped[str | None] = mapped_column(String(64))


class Consent(IdMixin, TimestampMixin, Base):
    """Согласия и отписки (B11)."""

    __tablename__ = "consents"

    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # marketing | pd_processing
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str | None] = mapped_column(String(64))  # mis | link | sms_stop


class Event(IdMixin, TimestampMixin, Base):
    """Принятое событие МИС. UNIQUE(event_id) — серверная идемпотентность B2."""

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_event_id"),)

    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    clinic_id: Mapped[str | None] = mapped_column(ForeignKey("clinics.id"))
    branch_external_id: Mapped[str | None] = mapped_column(String(64))
    patient_token: Mapped[str] = mapped_column(String(128), nullable=False)
    ordering_doctor_external_id: Mapped[str | None] = mapped_column(String(64))
    ready_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    raw_payload: Mapped[str | None] = mapped_column(Text)  # сырое тело для разбора инцидентов


class AuditEvent(IdMixin, Base):
    """Журнал: входы и действия. Пишется в B1, требование — «аудит пишет входы и действия».

    ВАЖНО: в payload не должно быть ПДн (телефонов, ФИО). Только id и мета.
    """

    __tablename__ = "audit_events"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[str | None] = mapped_column(Text)  # JSON без ПДн


class Outbox(IdMixin, TimestampMixin, Base):
    """Исходящие задачи (отправка SMS, вебхуки в CRM). Транзакционная надёжность.

    Пишем в outbox в той же транзакции, что и бизнес-действие; отдельный
    обработчик затем рассылает. Так ничего не теряется при падении процесса.
    """

    __tablename__ = "outbox"

    topic: Mapped[str] = mapped_column(String(32), nullable=False)  # sms | crm | notify
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PatientLink(IdMixin, Base):
    """Личная ссылка пациента (B6). В базе только HMAC токена, сам токен не хранится."""

    __tablename__ = "patient_links"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_patient_link_hash"),)

    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), nullable=False,
                                            index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                 nullable=False)


class GoalDoctor(Base):
    """Врачи цели визита (B6) в порядке клиники. Терапевта клиника кладёт первым."""

    __tablename__ = "goal_doctors"

    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), primary_key=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# Связи только там, где реально нужны (для удобных запросов B4/B6/B10).
Clinic.branches = relationship("Branch", backref="clinic", lazy="selectin")
Episode.patient = relationship("Patient", lazy="joined")
