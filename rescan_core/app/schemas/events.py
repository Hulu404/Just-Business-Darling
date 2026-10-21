"""Pydantic-схемы: контракт между МИС и rescan_core.

Контракт зафиксирован 15.10. Любое изменение полей ломает фронтенд и отчёт —
только через ревью с командой.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IngestStatus(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"


class ResultsReadyEvent(BaseModel):
    """Событие «анализы готовы» из МИС.

    Полей результатов анализа здесь нет и быть не должно — приходят только
    идентификаторы и время.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, max_length=128)
    branch_id: str = Field(..., min_length=1, max_length=64)
    patient_token: str = Field(..., min_length=1, max_length=128)
    phone: str = Field(..., min_length=5, max_length=32)
    ordering_doctor_id: str = Field(..., min_length=1, max_length=64)
    ready_at: datetime
    marketing_consent: bool

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) < 10:
            raise ValueError("phone: слишком мало цифр")
        return digits


class IngestResult(BaseModel):
    status: IngestStatus
    event_id: str
    episode_id: str | None = None
    group: str | None = None


class VisitRow(BaseModel):
    patient_token: str = Field(..., min_length=1, max_length=128)
    visit_date: datetime
    paid_amount: Decimal | None = Field(
        default=None, ge=0, le=Decimal("9999999999.99"), decimal_places=2,
        allow_inf_nan=False,
    )
    doctor_id: str | None = Field(default=None, max_length=64)


class CsvRowError(BaseModel):
    line_number: int
    message: str
    raw: str | None = None


class CsvUploadResult(BaseModel):
    accepted: int
    errors: list[CsvRowError]
