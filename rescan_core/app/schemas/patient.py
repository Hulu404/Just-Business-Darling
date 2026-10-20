"""Схемы API пациента (B6).

В ответах нет телефона пациента, `patient_token`, групп и данных о здоровье.
Тела запросов — `extra="forbid"`: лишние поля отклоняются.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

Code16 = Annotated[StrictStr, Field(min_length=1, max_length=16)]
Code64 = Annotated[StrictStr, Field(min_length=1, max_length=64)]
Title = Annotated[StrictStr, Field(min_length=1, max_length=255)]
EntityId = Annotated[StrictStr, Field(min_length=1, max_length=36)]


# --- настройки клиники (`clinics.patient_settings`) -------------------------

class BranchOption(BaseModel):
    code: Code16
    title: Title
    hint: StrictStr | None = None


class WindowOption(BaseModel):
    code: Code64
    title: Title


class PatientSettings(BaseModel):
    """Обязательны `timezone`, `branches`, `windows`, `texts`. Значений по умолчанию нет."""

    phone: StrictStr | None = None
    privacy_url: StrictStr | None = None
    timezone: Annotated[StrictStr, Field(min_length=1)]
    branches: Annotated[list[BranchOption], Field(min_length=1)]
    windows: Annotated[list[WindowOption], Field(min_length=1)]
    texts: dict[str, StrictStr]

    @field_validator("branches", "windows")
    @classmethod
    def unique_codes(cls, items: list) -> list:
        codes = [item.code for item in items]
        if len(set(codes)) != len(codes):
            raise ValueError("коды повторяются")
        return items


# --- ответы ------------------------------------------------------------------

class Theme(BaseModel):
    name: str | None
    logo_url: str | None
    accent: str | None


class ClinicInfo(BaseModel):
    name: str
    phone: str | None
    privacy_url: str | None
    theme: Theme


class DoctorStep(BaseModel):
    code: str
    retest_weeks: int | None
    due_date: date | None
    retest_state: Literal["before", "today", "overdue"] | None
    doctor_name: str | None


class GoalItem(BaseModel):
    id: str
    title: str


class Choice(BaseModel):
    branch_code: str | None
    goal_id: str


class RequestInfo(BaseModel):
    id: str
    status: Literal["accepted", "in_progress", "booked", "cancelled"]
    doctor_name: str | None
    format_title: str | None
    window_title: str | None
    created_at: datetime


class SessionResponse(BaseModel):
    """Не `active` — только `state`, `clinic` и `texts` (остальные поля не задаются)."""

    state: Literal["active", "expired", "stopped", "unsubscribed"]
    clinic: ClinicInfo
    consent_required: bool | None = None
    doctor_step: DoctorStep | None = None
    branches: list[BranchOption] | None = None
    goals: list[GoalItem] | None = None
    choice: Choice | None = None
    request: RequestInfo | None = None
    texts: dict[str, str]


class OkResponse(BaseModel):
    ok: bool = True


class DoctorItem(BaseModel):
    id: str
    name: str
    specialty: str | None
    photo_url: str | None
    tag: Literal["ordering", "visited"] | None


class DoctorsResponse(BaseModel):
    doctors: list[DoctorItem]


class FormatItem(BaseModel):
    id: str
    title: str
    price_kopecks: int | None
    currency: str
    has_payment: bool


class FormatsResponse(BaseModel):
    formats: list[FormatItem]
    windows: list[WindowOption]


class RequestCreated(BaseModel):
    request_id: str
    status: Literal["accepted"]
    payment_url: str | None


# --- тела запросов -------------------------------------------------------------

class ChoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_code: Code16 | None = None
    goal_id: EntityId


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doctor_id: EntityId
    format_id: EntityId
    window_code: Code64
