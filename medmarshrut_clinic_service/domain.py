"""Typed records for the clinic patient-card service."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PATIENT_STATUSES = {"active", "archived", "transferred", "deceased"}
REFERRAL_STATUSES = {"proposed", "accepted", "rejected", "cancelled", "completed"}
ANAMNESIS_KINDS = {"diagnosis", "allergy", "medication", "surgery", "family_history",
                   "risk_factor", "note", "measurement", "lab"}
AUTHOR_ROLES = {"physician", "coordinator", "nurse", "system"}
STUDY_TYPES = {"ct", "mr", "mammography", "xray"}


@dataclass(frozen=True)
class Clinic:
    id: str
    name: str
    network: str
    active: bool


@dataclass(frozen=True)
class Capability:
    id: int
    clinic_id: str
    study_type: str
    anatomy: str
    protocol_name: str
    finding_code: str  # "*" = any finding within this scope
    approved: bool


@dataclass(frozen=True)
class Partnership:
    id: int
    clinic_a: str
    clinic_b: str
    direction: str  # "outgoing" | "incoming" | "mutual"
    active: bool
    since: str


@dataclass(frozen=True)
class Patient:
    id: str
    home_clinic_id: str
    patient_ref: str
    full_name: str
    birth_date: str | None
    sex: str | None
    contact: str | None
    communication_channel: str | None
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AnamnesisEntry:
    id: str
    patient_id: str
    clinic_id: str
    recorded_at: str
    kind: str
    code: str | None
    text: str
    author_id: str
    author_role: str
    version: int
    shareable: bool


@dataclass(frozen=True)
class Referral:
    id: str
    patient_id: str
    from_clinic_id: str
    to_clinic_id: str
    reason: str
    status: str
    created_at: str
    created_by: str
    decided_at: str | None
    decided_by: str | None
    decision_note: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)