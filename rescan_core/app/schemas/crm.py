"""Входящие статусы CRM; неизвестные поля не принимаются."""
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RequestStatus = Literal["in_progress", "booked", "cancelled"]


class ManualStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: RequestStatus


class CrmStatus(ManualStatus):
    request_id: str | None = Field(default=None, min_length=1, max_length=36)
    crm_request_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def one_identifier(self) -> Self:
        supplied = self.model_fields_set & {"request_id", "crm_request_id"}
        if len(supplied) != 1 or not (self.request_id or self.crm_request_id):
            raise ValueError("Укажите один идентификатор заявки.")
        return self


class StatusResult(BaseModel):
    request_id: str
    status: str
