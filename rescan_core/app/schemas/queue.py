"""Схемы очереди врача (B4).

В ответах нет телефона, ФИО и данных о здоровье: только обезличенный токен,
филиал и сроки. Отметка — строго по одному эпизоду.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

MAX_RETEST_WEEKS = 52
RetestWeeks = Annotated[StrictInt, Field(ge=1, le=MAX_RETEST_WEEKS)]


class StepCode(StrEnum):
    """Фиксированный список шагов. Клиника включает подмножество и задаёт тексты."""

    DISCUSS = "discuss"
    RETEST = "retest"
    FOLLOWUP = "followup"


class StepOption(BaseModel):
    """Шаг из настроек клиники (`clinics.step_options`)."""

    model_config = ConfigDict(extra="forbid")

    code: StepCode
    title: str = Field(..., min_length=1, max_length=255)
    weeks: list[RetestWeeks] | None = None

    @model_validator(mode="after")
    def weeks_only_for_retest(self) -> StepOption:
        if self.code is StepCode.RETEST:
            if not self.weeks:
                raise ValueError("retest: нужен непустой список недель")
            if len(set(self.weeks)) != len(self.weeks):
                raise ValueError("retest: недели повторяются")
        elif self.weeks is not None:
            raise ValueError("weeks: только для retest")
        return self


class StepOptionsResponse(BaseModel):
    options: list[StepOption]


class QueueItem(BaseModel):
    episode_id: str
    patient_token: str
    branch_name: str | None
    ready_at: datetime
    queue_deadline_at: datetime


class QueueResponse(BaseModel):
    server_time: datetime
    items: list[QueueItem]


class StepMarkRequest(BaseModel):
    """Тело отметки. Лишние поля, в том числе списки эпизодов, отклоняются."""

    model_config = ConfigDict(extra="forbid")

    code: StepCode
    retest_weeks: StrictInt | None = None


class StepMarkResult(BaseModel):
    episode_id: str
    step_id: str
    status: str
