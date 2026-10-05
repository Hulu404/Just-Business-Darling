"""Demo-role sessions: one cookie per role."""
from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from errors import GatewayError

ROLES = ("patient", "staff", "doctor", "partner", "pharmacy")
SESSION_TTL = 12 * 3600


def cookie_name(role: str) -> str:
    return f"mm_session_{role}"


@dataclass(frozen=True)
class Session:
    id: str
    role: str
    person_id: str
    name: str
    clinic_id: str | None
    patient_ref: str | None
    created_at: float

    def public(self) -> dict:
        result = {"role": self.role, "name": self.name}
        if self.role == "patient":
            result["patient_ref"] = self.patient_ref
        else:
            result["clinic_id"] = self.clinic_id
        return result

    @property
    def actor(self) -> str:
        return self.person_id


def ensure_owner(session: Session, patient_ref: str | None) -> None:
    if session.role == "patient" and (not patient_ref or patient_ref != session.patient_ref):
        raise GatewayError(404, "not_found", "Не нашли то, что запрошено. Обновите страницу.")


class People:
    def __init__(self, path: Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.staff = {p["id"]: p for p in data["staff"]}
        self.patients = {p["patient_ref"]: p for p in data["patients"]}
        self.roles = data["roles"]
        for key in ("staff", "doctor"):
            if self.roles[key] not in self.staff:
                raise ValueError(f"people file: role {key} refers to an unknown person")

    def person(self, person_id: str) -> dict:
        return self.staff[person_id]

    def partner(self, clinic_id: str) -> dict | None:
        person_id = self.roles.get("partner", {}).get(clinic_id)
        return self.staff.get(person_id) if person_id else None


class SessionStore:
    def __init__(self, ttl: float = SESSION_TTL):
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()
        self.ttl = ttl

    def create(self, role: str, *, person_id: str, name: str, clinic_id: str | None = None,
               patient_ref: str | None = None) -> Session:
        session = Session(secrets.token_urlsafe(32), role, person_id, name, clinic_id, patient_ref, time.time())
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, role: str, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
            if session and time.time() - session.created_at > self.ttl:
                del self._sessions[session_id]
                return None
        return session if session and session.role == role else None

    def delete(self, session_id: str | None) -> None:
        with self._lock:
            self._sessions.pop(session_id or "", None)