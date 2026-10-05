"""Typed records for the patient pathway service."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SourceReport:
    id: str
    source_service: str
    source_report_id: str
    source_report_version: int
    study_type: str
    study_uid: str
    patient_ref: str | None
    anatomy: str
    protocol_name: str
    finding_code: str
    conclusion: str
    confidence: float | None
    source_model: str
    physician_id: str
    confirmed_at: str
    confirmation_status: str


@dataclass(frozen=True)
class PlanStep:
    id: str
    episode_id: str
    position: int
    kind: str
    description: str
    status: str
    completed_at: str | None
    owner: str = "coordinator"
    due_at: str | None = None
    continue_on: str = "confirmed_outcome"
    decision_source: str = ""
    cycle: int = 1
    appointment_at: str | None = None
    stop_reason: str | None = None


@dataclass(frozen=True)
class AuditEvent:
    id: int
    episode_id: str
    event_type: str
    actor: str
    occurred_at: str
    details: dict[str, Any]


@dataclass(frozen=True)
class Episode:
    id: str
    status: str
    source_report: SourceReport
    plan_steps: tuple[PlanStep, ...]
    audit_events: tuple[AuditEvent, ...]
    rule_version: str | None
    manual_reason: str | None
    created_at: str
    updated_at: str
    closed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
