"""API пациента по личной ссылке (B6).

Порядок проверок на каждом пути: ссылка (404) → настройки клиники (503) →
состояние (409 `not_active`) → согласие (409) → выбор цели (409). Неизвестная,
отозванная ссылка и ссылка эпизода контрольной группы неотличимы друг от друга.
Время передаётся параметром; в базе — UTC, даты пациента — в поясе клиники.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Clinic, Consent, Episode, Outbox, Patient, PatientLink, Request
from app.repositories.patient_repository import PD_PROCESSING, PatientRepository
from app.schemas.patient import (
    BranchOption,
    Choice,
    ChoiceRequest,
    ClinicInfo,
    DoctorItem,
    DoctorsResponse,
    DoctorStep,
    FormatItem,
    FormatsResponse,
    GoalItem,
    OkResponse,
    PatientSettings,
    RequestCreate,
    RequestCreated,
    RequestInfo,
    SessionResponse,
    Theme,
)
from app.security.patient_link import hash_token, looks_like_token, new_token
from app.services import audit
from app.services.queue_service import as_utc

PATIENT_ROLE = "patient"
RETEST = "retest"
CONTROL_GROUP = "control"

LinkState = Literal["active", "expired", "stopped", "unsubscribed"]
RetestState = Literal["before", "today", "overdue"]

# Статус заявки → статус для пациента.
PATIENT_STATUS = {"new": "accepted", "sent": "accepted", "in_progress": "in_progress",
                  "booked": "booked", "cancelled": "cancelled"}

MESSAGES = {
    "link_not_found": "Ссылка не найдена. Откройте ссылку из сообщения ещё раз или "
                      "позвоните в клинику.",
    "not_active": "Запись по этой ссылке сейчас недоступна. Обновите страницу или "
                  "позвоните в клинику.",
    "consent_required": "Сначала подтвердите согласие на обработку данных на первом экране.",
    "choice_required": "Сначала выберите цель визита.",
    "request_exists": "Заявка уже оставлена. Её статус — на странице заявки.",
    "invalid_input": "Проверьте выбор и отправьте ещё раз.",
    "not_configured": "Страница клиники ещё не настроена. Чтобы записаться к врачу, "
                      "позвоните в клинику.",
}


def patient_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": MESSAGES[code]})


def https_or_none(value: str | None) -> str | None:
    return value if isinstance(value, str) and value.startswith("https://") else None


def parse_patient_settings(raw: str | None) -> tuple[PatientSettings, ZoneInfo]:
    """Неполные или испорченные настройки — 503, без значений по умолчанию."""
    try:
        settings = PatientSettings.model_validate(json.loads(raw or "null"))
        zone = ZoneInfo(settings.timezone)
    except (ValueError, ValidationError, ZoneInfoNotFoundError) as exc:
        raise patient_error(503, "not_configured") from exc
    return settings, zone


def issue_link(session: Session, episode_id: str, now: datetime) -> str:
    """Выдать ссылку эпизоду основной группы. Токен возвращается один раз и не хранится."""
    episode = session.get(Episode, episode_id)
    if episode is None or episode.group == CONTROL_GROUP:
        raise LookupError("Эпизод не найден или не получает сообщений.")
    token = new_token()
    ttl = timedelta(days=get_settings().patient_link_ttl_days)
    session.add(PatientLink(episode_id=episode.id, token_hash=hash_token(token),
                            expires_at=as_utc(now) + ttl, created_at=as_utc(now)))
    session.commit()
    return token


@dataclass(frozen=True)
class LinkContext:
    link: PatientLink
    episode: Episode
    patient: Patient
    clinic: Clinic
    settings: PatientSettings
    zone: ZoneInfo
    state: LinkState


class PatientService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = PatientRepository(session)

    # --- общие проверки ---

    def check_link(self, token: str | None) -> tuple[PatientLink, Episode, Patient, Clinic]:
        """Ссылка действует для эпизода основной группы, иначе одинаковый 404."""
        if not looks_like_token(token):
            raise patient_error(404, "link_not_found")
        link = self.repo.find_link(hash_token(token or ""))
        episode = self.repo.get_episode(link.episode_id) if link else None
        if link is None or link.revoked_at is not None or episode is None \
                or episode.group == CONTROL_GROUP:
            raise patient_error(404, "link_not_found")
        patient = self.session.get(Patient, episode.patient_id)
        clinic = self.repo.get_clinic(patient.clinic_id) if patient else None
        if patient is None or clinic is None:
            raise patient_error(404, "link_not_found")
        return link, episode, patient, clinic

    def _context(self, token: str | None, now: datetime) -> LinkContext:
        link, episode, patient, clinic = self.check_link(token)
        settings, zone = parse_patient_settings(clinic.patient_settings)
        return LinkContext(link, episode, patient, clinic, settings, zone,
                           _state(link, patient, clinic, now))

    def _active(self, token: str | None, now: datetime, *, consent: bool = True,
                choice: bool = False) -> LinkContext:
        ctx = self._context(token, now)
        if ctx.state != "active":
            raise patient_error(409, "not_active")
        if consent and not self.repo.has_consent(ctx.patient.id):
            raise patient_error(409, "consent_required")
        if choice and ctx.episode.chosen_goal_id is None:
            raise patient_error(409, "choice_required")
        return ctx

    # --- GET /session ---

    def session_info(self, token: str | None, *, now: datetime) -> SessionResponse:
        ctx = self._context(token, now)
        clinic = _clinic_info(ctx)
        if ctx.state != "active":
            return SessionResponse(state=ctx.state, clinic=clinic, texts=ctx.settings.texts)
        episode = ctx.episode
        choice = None
        if episode.chosen_goal_id is not None:
            choice = Choice(branch_code=episode.chosen_branch, goal_id=episode.chosen_goal_id)
        return SessionResponse(
            state="active",
            clinic=clinic,
            consent_required=not self.repo.has_consent(ctx.patient.id),
            doctor_step=self._doctor_step(ctx, now),
            # Явная копия: при `exclude_unset` поле `hint` без значения не пропадёт из ответа.
            branches=[BranchOption(code=item.code, title=item.title, hint=item.hint)
                      for item in ctx.settings.branches],
            goals=[GoalItem(id=goal.id, title=goal.title)
                   for goal in self.repo.active_goals(ctx.clinic.id)],
            choice=choice,
            request=self._request_info(ctx),
            texts=ctx.settings.texts,
        )

    def _doctor_step(self, ctx: LinkContext, now: datetime) -> DoctorStep | None:
        found = self.repo.latest_doctor_step(ctx.episode.id)
        if found is None:
            return None
        step, doctor_name = found
        weeks: int | None = None
        due: date | None = None
        state: RetestState | None = None
        if step.kind == RETEST and step.due_date is not None and step.set_at is not None:
            weeks = (as_utc(step.due_date) - as_utc(step.set_at)).days // 7
            due = as_utc(step.due_date).astimezone(ctx.zone).date()
            state = _retest_state(due, as_utc(now).astimezone(ctx.zone).date())
        return DoctorStep(code=step.kind, retest_weeks=weeks, due_date=due,
                          retest_state=state, doctor_name=doctor_name)

    def _request_info(self, ctx: LinkContext) -> RequestInfo | None:
        request = self.repo.latest_request(ctx.episode.id)
        if request is None:
            return None
        windows = {window.code: window.title for window in ctx.settings.windows}
        return RequestInfo(
            id=request.id,
            status=PATIENT_STATUS.get(request.status, "accepted"),  # type: ignore[arg-type]
            doctor_name=self.repo.doctor_name(request.doctor_id),
            format_title=self.repo.format_title(request.format_id),
            window_title=windows.get(request.window or ""),
            created_at=as_utc(request.created_at),
        )

    # --- POST /consent ---

    def consent(self, token: str | None, *, now: datetime) -> OkResponse:
        ctx = self._active(token, now, consent=False)
        if not self.repo.has_consent(ctx.patient.id):
            self.session.add(Consent(patient_id=ctx.patient.id, kind=PD_PROCESSING,
                                     granted=True, source="link"))
            audit.record(self.session, action="patient.consent", role=PATIENT_ROLE,
                         entity="episode", entity_id=ctx.episode.id)
            self.session.commit()
        return OkResponse()

    # --- POST /choice ---

    def choose(self, token: str | None, body: ChoiceRequest, *, now: datetime) -> OkResponse:
        ctx = self._active(token, now)
        has_step = self.repo.latest_doctor_step(ctx.episode.id) is not None
        branch_codes = {branch.code for branch in ctx.settings.branches}
        if has_step and body.branch_code is not None:
            raise patient_error(422, "invalid_input")
        if not has_step and body.branch_code not in branch_codes:
            raise patient_error(422, "invalid_input")
        goal_ids = {goal.id for goal in self.repo.active_goals(ctx.clinic.id)}
        if body.goal_id not in goal_ids:
            raise patient_error(422, "invalid_input")
        ctx.episode.chosen_branch = body.branch_code
        ctx.episode.chosen_goal_id = body.goal_id
        self.session.commit()
        return OkResponse()

    # --- GET /doctors ---

    def doctors(self, token: str | None, *, now: datetime) -> DoctorsResponse:
        ctx = self._active(token, now, choice=True)
        return DoctorsResponse(doctors=self._ordered_doctors(ctx))

    def _ordered_doctors(self, ctx: LinkContext) -> list[DoctorItem]:
        """Назначивший → у кого пациент уже был (сначала последний визит) → по порядку цели."""
        clinic_id = ctx.clinic.id
        result: list[DoctorItem] = []
        seen: set[str] = set()

        def add(doctor, tag) -> None:
            seen.add(doctor.id)
            result.append(DoctorItem(id=doctor.id, name=doctor.full_name,
                                     specialty=doctor.specialty, photo_url=doctor.photo_url,
                                     tag=tag))

        ordering = self.repo.active_doctor(clinic_id, ctx.episode.ordering_doctor_id)
        if ordering is not None:
            add(ordering, "ordering")
        goal_doctors = [doctor for doctor, _ in
                        self.repo.goal_doctors(clinic_id, ctx.episode.chosen_goal_id or "")]
        visits = self.repo.last_visits(clinic_id, ctx.patient.patient_token)
        visited = sorted((d for d in goal_doctors if d.external_id in visits),
                         key=lambda d: as_utc(visits[d.external_id]), reverse=True)
        for doctor in visited:
            if doctor.id not in seen:
                add(doctor, "visited")
        for doctor in goal_doctors:
            if doctor.id not in seen:
                add(doctor, None)
        return result

    # --- GET /formats ---

    def formats(self, token: str | None, *, now: datetime) -> FormatsResponse:
        ctx = self._active(token, now, choice=True)
        return FormatsResponse(
            formats=[FormatItem(id=item.id, title=item.title, price_kopecks=item.price_kopecks,
                                currency=item.currency,
                                has_payment=https_or_none(item.payment_url) is not None)
                     for item in self.repo.active_formats(ctx.clinic.id)],
            windows=ctx.settings.windows,
        )

    # --- POST /requests ---

    def create_request(self, token: str | None, body: RequestCreate, *,
                       now: datetime) -> RequestCreated:
        now = as_utc(now)
        ctx = self._active(token, now, choice=True)
        doctor_ids = {doctor.id for doctor in self._ordered_doctors(ctx)}
        chosen_format = self.repo.active_format(ctx.clinic.id, body.format_id)
        window_codes = {window.code for window in ctx.settings.windows}
        if body.doctor_id not in doctor_ids or chosen_format is None \
                or body.window_code not in window_codes:
            raise patient_error(422, "invalid_input")

        self.repo.lock_episode(ctx.episode.id, now)
        if self.repo.has_open_request(ctx.episode.id):
            self.session.rollback()
            raise patient_error(409, "request_exists")
        request = Request(episode_id=ctx.episode.id, patient_id=ctx.patient.id,
                          doctor_id=body.doctor_id, format_id=chosen_format.id,
                          goal_id=ctx.episode.chosen_goal_id, window=body.window_code,
                          status="new", created_at=now, updated_at=now)
        self.session.add(request)
        self.session.flush()
        self.session.add(Outbox(topic="crm", payload=json.dumps({"request_id": request.id}),
                                available_at=now))
        audit.record(self.session, action="patient.request_created", role=PATIENT_ROLE,
                     entity="episode", entity_id=ctx.episode.id,
                     payload={"request_id": request.id})
        self.session.commit()
        return RequestCreated(request_id=request.id, status="accepted",
                              payment_url=https_or_none(chosen_format.payment_url))


def _state(link: PatientLink, patient: Patient, clinic: Clinic,
           now: datetime) -> LinkState:
    if patient.opted_out:
        return "unsubscribed"
    if not clinic.service_enabled:
        return "stopped"
    if as_utc(link.expires_at) <= as_utc(now):
        return "expired"
    return "active"


def _retest_state(due: date, today: date) -> RetestState:
    if today < due:
        return "before"
    return "today" if today == due else "overdue"


def _clinic_info(ctx: LinkContext) -> ClinicInfo:
    try:
        theme = json.loads(ctx.clinic.theme or "{}")
    except ValueError:
        theme = {}
    if not isinstance(theme, dict):
        theme = {}

    def text_or_none(key: str) -> str | None:
        value = theme.get(key)
        return value if isinstance(value, str) else None

    return ClinicInfo(
        name=ctx.clinic.name,
        phone=ctx.settings.phone,
        privacy_url=https_or_none(ctx.settings.privacy_url),
        theme=Theme(name=text_or_none("name"), logo_url=text_or_none("logo_url"),
                    accent=text_or_none("accent")),
    )
