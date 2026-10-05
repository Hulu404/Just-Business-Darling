"""Typed records for the medication marketplace service."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


ORDER_STATUSES = {"placed", "confirmed", "ready", "picked_up", "cancelled", "failed"}
PRESCRIPTION_STATUSES = {"active", "expired", "cancelled", "completed"}
FORM_KINDS = {"tablet", "capsule", "solution", "suspension", "cream", "ointment",
              "inhaler", "injection", "drops", "spray"}


@dataclass(frozen=True)
class Pharmacy:
    id: str
    name: str
    network: str
    city: str
    active: bool
    order_url_template: str


@dataclass(frozen=True)
class Medication:
    id: str
    inn: str
    trade_name: str
    form: str
    strength: str
    atc_code: str | None
    prescription_required: bool
    active: bool

    @property
    def analog_key(self) -> tuple[str, str, str]:
        return (self.inn.lower().strip(), self.form.lower().strip(), self.strength.lower().strip())


@dataclass(frozen=True)
class Inventory:
    pharmacy_id: str
    medication_id: str
    stock: int
    price: float
    currency: str
    updated_at: str


@dataclass(frozen=True)
class PrescriptionItem:
    position: int
    inn: str
    trade_name: str | None
    form: str
    strength: str
    dosage: str
    duration_days: int
    quantity: int
    substitution_allowed: bool


@dataclass(frozen=True)
class Prescription:
    id: str
    source_prescription_id: str
    source_version: int
    patient_ref: str
    physician_id: str
    confirmed_at: str
    expires_at: str
    conclusion: str
    study_uid: str
    status: str
    created_at: str
    items: tuple[PrescriptionItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderItem:
    medication_id: str
    trade_name: str
    quantity: int
    unit_price: float
    currency: str


@dataclass(frozen=True)
class Order:
    id: str
    prescription_id: str
    patient_ref: str
    pharmacy_id: str
    status: str
    total: float
    currency: str
    items: tuple[OrderItem, ...]
    created_at: str
    updated_at: str
    redirect_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)