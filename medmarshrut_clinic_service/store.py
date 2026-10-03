"""SQLite repository for patients, anamnesis, referrals, routing candidates."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from domain import (ANAMNESIS_KINDS, AUTHOR_ROLES, PATIENT_STATUSES, REFERRAL_STATUSES,
                    AnamnesisEntry, Patient, Referral)
from network import ClinicNetwork


REF_RE = re.compile(r"[A-Za-z0-9_.:-]{2,128}")


class ClinicError(ValueError):
    pass


class ConflictError(ClinicError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, name, *, max_length: int, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ClinicError(f"{name} is required")
        return None
    if not isinstance(value, str):
        raise ClinicError(f"Invalid {name}")
    value = value.strip()
    if required and not value:
        raise ClinicError(f"{name} is required")
    if len(value) > max_length:
        raise ClinicError(f"{name} too long")
    return value


def _iso(value, name, *, date_only: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ClinicError(f"Invalid {name}")
    try:
        parsed = date.fromisoformat(value) if date_only else datetime.fromisoformat(value)
    except ValueError:
        raise ClinicError(f"Invalid {name}") from None
    if not date_only and parsed.tzinfo is None:
        raise ClinicError(f"{name} needs a time zone")
    return parsed.isoformat()


class ClinicStore:
    def __init__(self, db_path: Path, network: ClinicNetwork):
        self.network = network
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY, home_clinic_id TEXT NOT NULL, patient_ref TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL, birth_date TEXT, sex TEXT, contact TEXT, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS anamnesis (
                id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id),
                clinic_id TEXT NOT NULL, recorded_at TEXT NOT NULL, kind TEXT NOT NULL,
                code TEXT, text TEXT NOT NULL, author_id TEXT NOT NULL, author_role TEXT NOT NULL,
                version INTEGER NOT NULL, shareable INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS referrals (
                id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id),
                from_clinic_id TEXT NOT NULL, to_clinic_id TEXT NOT NULL, reason TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
                decided_at TEXT, decided_by TEXT, decision_note TEXT);
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, event_type TEXT NOT NULL,
                actor TEXT NOT NULL, occurred_at TEXT NOT NULL, details_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_patients_ref ON patients(patient_ref);
            CREATE INDEX IF NOT EXISTS idx_anamnesis_patient ON anamnesis(patient_id);
            CREATE INDEX IF NOT EXISTS idx_referrals_patient ON referrals(patient_id);
            CREATE INDEX IF NOT EXISTS idx_referrals_to ON referrals(to_clinic_id);
        """)

    def close(self) -> None:
        with self._lock:
            self.db.close()

    # ---------- audit ----------

    def _event(self, patient_id: str | None, event_type: str, actor: str, details: dict) -> None:
        self.db.execute("INSERT INTO audit_events(patient_id,event_type,actor,occurred_at,details_json) VALUES(?,?,?,?,?)",
                        (patient_id, event_type, actor, now(), json.dumps(details, ensure_ascii=False, sort_keys=True)))

    # ---------- patients ----------

    def create_patient(self, home_clinic_id: str, payload: dict) -> Patient:
        if not isinstance(payload, dict) or set(payload) != {"patient_ref", "full_name", "birth_date", "sex", "contact"}:
            raise ClinicError("Invalid patient fields")
        if home_clinic_id not in self.network.clinics or not self.network.clinics[home_clinic_id]["active"]:
            raise ClinicError("Unknown or inactive home clinic")
        ref = _text(payload["patient_ref"], "patient_ref", max_length=128)
        if not REF_RE.fullmatch(ref):
            raise ClinicError("Invalid patient_ref")
        full_name = _text(payload["full_name"], "full_name", max_length=256)
        birth_date = _iso(payload["birth_date"], "birth_date", date_only=True)
        sex = payload["sex"]
        if sex is not None and sex not in {"M", "F", "X"}:
            raise ClinicError("Invalid sex")
        contact = _text(payload["contact"], "contact", max_length=256, required=False)
        stamp = now()
        patient_id = uuid.uuid4().hex
        with self._lock, self.db:
            if self.db.execute("SELECT 1 FROM patients WHERE patient_ref=?", (ref,)).fetchone():
                raise ConflictError("patient_ref already registered")
            self.db.execute("INSERT INTO patients VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (patient_id, home_clinic_id, ref, full_name, birth_date, sex, contact, "active", stamp, stamp))
            self._event(patient_id, "patient_registered", home_clinic_id, {"home_clinic_id": home_clinic_id})
            return self.get_patient(patient_id)

    def get_patient(self, patient_id: str) -> Patient | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
            return Patient(**dict(row)) if row else None

    def get_patient_by_ref(self, patient_ref: str) -> Patient | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM patients WHERE patient_ref=?", (patient_ref,)).fetchone()
            return Patient(**dict(row)) if row else None

    def list_patients(self, clinic_id: str | None, status: str | None = None, limit: int = 100) -> list[Patient]:
        if limit < 1 or limit > 500:
            raise ClinicError("Invalid limit")
        with self._lock:
            query = "SELECT * FROM patients WHERE 1=1"
            args: list = []
            if clinic_id:
                query += " AND home_clinic_id=?"
                args.append(clinic_id)
            if status:
                if status not in PATIENT_STATUSES:
                    raise ClinicError("Invalid status filter")
                query += " AND status=?"
                args.append(status)
            query += " ORDER BY updated_at DESC LIMIT ?"
            args.append(limit)
            return [Patient(**dict(r)) for r in self.db.execute(query, args)]

    def set_patient_status(self, patient_id: str, clinic_id: str, status: str, actor: str) -> Patient:
        if status not in PATIENT_STATUSES:
            raise ClinicError("Invalid status")
        actor = _text(actor, "actor", max_length=128)
        with self._lock, self.db:
            patient = self.get_patient(patient_id)
            if not patient:
                raise ClinicError("Patient not found")
            if patient.home_clinic_id != clinic_id:
                raise ConflictError("Only home clinic can change patient status")
            if patient.status == status:
                return patient
            if patient.status == "deceased":
                raise ConflictError("Patient is deceased; status is final")
            stamp = now()
            self.db.execute("UPDATE patients SET status=?,updated_at=? WHERE id=?", (status, stamp, patient_id))
            self._event(patient_id, "status_changed", actor, {"from": patient.status, "to": status})
            return self.get_patient(patient_id)

    # ---------- anamnesis ----------

    def add_anamnesis(self, patient_id: str, clinic_id: str, actor: str, author_role: str, payload: dict) -> AnamnesisEntry:
        if not isinstance(payload, dict) or set(payload) != {"kind", "code", "text", "shareable", "recorded_at"}:
            raise ClinicError("Invalid anamnesis fields")
        if payload["kind"] not in ANAMNESIS_KINDS:
            raise ClinicError("Invalid anamnesis kind")
        if author_role not in AUTHOR_ROLES:
            raise ClinicError("Invalid author role")
        code = _text(payload["code"], "code", max_length=64, required=False)
        text = _text(payload["text"], "text", max_length=4000)
        if type(payload["shareable"]) is not bool:
            raise ClinicError("shareable must be boolean")
        recorded_at = _iso(payload["recorded_at"], "recorded_at") or now()
        with self._lock, self.db:
            patient = self.get_patient(patient_id)
            if not patient:
                raise ClinicError("Patient not found")
            if patient.home_clinic_id != clinic_id:
                raise ConflictError("Only home clinic can append anamnesis")
            if patient.status in {"archived", "deceased"}:
                raise ConflictError("Patient record is closed for new entries")
            previous = self.db.execute("SELECT MAX(version) AS v FROM anamnesis WHERE patient_id=?", (patient_id,)).fetchone()
            version = (previous["v"] or 0) + 1
            entry_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO anamnesis VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (entry_id, patient_id, clinic_id, recorded_at, payload["kind"], code, text,
                             actor, author_role, version, 1 if payload["shareable"] else 0))
            self.db.execute("UPDATE patients SET updated_at=? WHERE id=?", (now(), patient_id))
            self._event(patient_id, "anamnesis_added", actor, {"kind": payload["kind"], "code": code,
                                                               "version": version, "shareable": payload["shareable"]})
            return self._row_to_anamnesis(self.db.execute("SELECT * FROM anamnesis WHERE id=?", (entry_id,)).fetchone())

    @staticmethod
    def _row_to_anamnesis(row: sqlite3.Row) -> AnamnesisEntry:
        data = dict(row)
        data["shareable"] = bool(data["shareable"])
        return AnamnesisEntry(**data)

    def list_anamnesis(self, patient_id: str) -> list[AnamnesisEntry]:
        with self._lock:
            return [self._row_to_anamnesis(r) for r in self.db.execute(
                "SELECT * FROM anamnesis WHERE patient_id=? ORDER BY version", (patient_id,))]

    # ---------- referrals ----------

    def create_referral(self, patient_id: str, from_clinic_id: str, to_clinic_id: str,
                        reason: str, created_by: str) -> Referral:
        reason = _text(reason, "reason", max_length=1000)
        created_by = _text(created_by, "created_by", max_length=128)
        if from_clinic_id == to_clinic_id:
            raise ClinicError("Referral target must differ from source")
        with self._lock, self.db:
            patient = self.get_patient(patient_id)
            if not patient:
                raise ClinicError("Patient not found")
            if patient.home_clinic_id != from_clinic_id:
                raise ConflictError("Referral must originate from the home clinic")
            if patient.status != "active":
                raise ConflictError("Only active patients can be referred")
            if to_clinic_id not in self.network.partners_of(from_clinic_id):
                raise ConflictError("Target clinic is not an active partner")
            existing = self.db.execute(
                "SELECT 1 FROM referrals WHERE patient_id=? AND from_clinic_id=? AND to_clinic_id=? "
                "AND status IN ('proposed','accepted')",
                (patient_id, from_clinic_id, to_clinic_id)).fetchone()
            if existing:
                raise ConflictError("Active referral already exists for this pair")
            referral_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO referrals VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (referral_id, patient_id, from_clinic_id, to_clinic_id, reason, "proposed",
                             now(), created_by, None, None, None))
            self._event(patient_id, "referral_proposed", created_by,
                        {"referral_id": referral_id, "to_clinic_id": to_clinic_id})
            return self._row_to_referral(self.db.execute("SELECT * FROM referrals WHERE id=?", (referral_id,)).fetchone())

    @staticmethod
    def _row_to_referral(row: sqlite3.Row) -> Referral:
        return Referral(**dict(row))

    def referral_action(self, referral_id: str, action: str, clinic_id: str, actor: str,
                        note: str | None) -> Referral:
        if action not in {"accept", "reject", "cancel", "complete"}:
            raise ClinicError("Invalid action")
        actor = _text(actor, "actor", max_length=128)
        note = _text(note, "note", max_length=1000, required=False)
        with self._lock, self.db:
            row = self.db.execute("SELECT * FROM referrals WHERE id=?", (referral_id,)).fetchone()
            if not row:
                raise ClinicError("Referral not found")
            referral = self._row_to_referral(row)
            if action == "accept" or action == "reject":
                if referral.to_clinic_id != clinic_id:
                    raise ConflictError("Only target clinic can accept or reject")
                if referral.status != "proposed":
                    raise ConflictError("Referral is not proposed")
                new_status = "accepted" if action == "accept" else "rejected"
            elif action == "cancel":
                if referral.from_clinic_id != clinic_id:
                    raise ConflictError("Only source clinic can cancel")
                if referral.status not in {"proposed", "accepted"}:
                    raise ConflictError("Referral cannot be cancelled")
                new_status = "cancelled"
            else:  # complete
                if referral.to_clinic_id != clinic_id:
                    raise ConflictError("Only target clinic can complete")
                if referral.status != "accepted":
                    raise ConflictError("Referral must be accepted first")
                new_status = "completed"
            self.db.execute("UPDATE referrals SET status=?,decided_at=?,decided_by=?,decision_note=? WHERE id=?",
                            (new_status, now(), actor, note, referral_id))
            self._event(referral.patient_id, f"referral_{new_status}", actor,
                        {"referral_id": referral_id, "note": note})
            return self._row_to_referral(self.db.execute("SELECT * FROM referrals WHERE id=?", (referral_id,)).fetchone())

    def list_referrals(self, *, patient_id: str | None = None, clinic_id: str | None = None,
                       status: str | None = None) -> list[Referral]:
        with self._lock:
            query = "SELECT * FROM referrals WHERE 1=1"
            args: list = []
            if patient_id:
                query += " AND patient_id=?"
                args.append(patient_id)
            if clinic_id:
                query += " AND (from_clinic_id=? OR to_clinic_id=?)"
                args.extend([clinic_id, clinic_id])
            if status:
                if status not in REFERRAL_STATUSES:
                    raise ClinicError("Invalid referral status")
                query += " AND status=?"
                args.append(status)
            query += " ORDER BY created_at DESC"
            return [self._row_to_referral(r) for r in self.db.execute(query, args)]

    # ---------- routing ----------

    def route_candidates(self, patient_ref: str, scope: dict) -> dict:
        required = {"study_type", "anatomy", "protocol_name", "finding_code"}
        if not isinstance(scope, dict) or set(scope) != required:
            raise ClinicError("Invalid routing scope")
        for key, value in scope.items():
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ClinicError(f"Invalid {key}")
        patient = self.get_patient_by_ref(patient_ref)
        if not patient:
            return {"patient_ref": patient_ref, "candidates": [], "reason": "unknown_patient_ref"}
        if patient.status != "active":
            return {"patient_ref": patient_ref, "candidates": [], "reason": f"patient_{patient.status}"}
        home = patient.home_clinic_id
        candidates = []
        if self._has_capability(home, scope):
            candidates.append(self._candidate(home, scope, role="home", referral_required=False))
        for partner in self.network.partners_of(home):
            if self._has_capability(partner, scope):
                candidates.append(self._candidate(partner, scope, role="partner", referral_required=True))
        if not candidates:
            return {"patient_ref": patient_ref, "home_clinic_id": home, "candidates": [],
                    "reason": "no_clinic_with_capability"}
        return {"patient_ref": patient_ref, "home_clinic_id": home, "candidates": candidates, "reason": None}

    def _has_capability(self, clinic_id: str, scope: dict) -> bool:
        for cap in self.network.capabilities_for(clinic_id):
            if (cap["approved"] and cap["study_type"] == scope["study_type"]
                    and cap["anatomy"] == scope["anatomy"] and cap["protocol_name"] == scope["protocol_name"]
                    and cap["finding_code"] in {scope["finding_code"], "*"}):
                return True
        return False

    def _candidate(self, clinic_id: str, scope: dict, *, role: str, referral_required: bool) -> dict:
        clinic = self.network.clinics[clinic_id]
        matched = next(c for c in self.network.capabilities_for(clinic_id)
                       if c["approved"] and c["study_type"] == scope["study_type"]
                       and c["anatomy"] == scope["anatomy"] and c["protocol_name"] == scope["protocol_name"]
                       and c["finding_code"] in {scope["finding_code"], "*"})
        return {"clinic_id": clinic_id, "clinic_name": clinic["name"], "network": clinic["network"],
                "role": role, "referral_required": referral_required,
                "matched_capability": {"study_type": matched["study_type"], "anatomy": matched["anatomy"],
                                       "protocol_name": matched["protocol_name"], "finding_code": matched["finding_code"]}}

    # ---------- card / visibility ----------

    def patient_card(self, patient_id: str, viewer_clinic_id: str) -> dict | None:
        with self._lock:
            patient = self.get_patient(patient_id)
            if not patient:
                return None
            if patient.home_clinic_id == viewer_clinic_id:
                return self._full_card(patient)
            return self._partner_card(patient, viewer_clinic_id)

    def _full_card(self, patient: Patient) -> dict:
        anamnesis = self.list_anamnesis(patient.id)
        referrals = self.list_referrals(patient_id=patient.id)
        shared_with = sorted({r.to_clinic_id for r in referrals if r.status in {"accepted", "completed"}})
        return {
            "visibility": "home",
            "patient": {"id": patient.id, "patient_ref": patient.patient_ref,
                        "home_clinic_id": patient.home_clinic_id,
                        "home_clinic_name": self.network.clinics[patient.home_clinic_id]["name"],
                        "full_name": patient.full_name, "birth_date": patient.birth_date,
                        "sex": patient.sex, "contact": patient.contact, "status": patient.status},
            "anamnesis": [self._entry_dict(a) for a in anamnesis],
            "referrals": [r.to_dict() for r in referrals],
            "shared_with": [{"clinic_id": c, "clinic_name": self.network.clinics[c]["name"]} for c in shared_with],
        }

    def _partner_card(self, patient: Patient, viewer_clinic_id: str) -> dict | None:
        referral = self.db.execute(
            "SELECT * FROM referrals WHERE patient_id=? AND from_clinic_id=? AND to_clinic_id=? "
            "AND status IN ('proposed','accepted','completed') ORDER BY created_at DESC LIMIT 1",
            (patient.id, patient.home_clinic_id, viewer_clinic_id)).fetchone()
        if not referral:
            return None
        referral_obj = self._row_to_referral(referral)
        shared = [a for a in self.list_anamnesis(patient.id) if a.shareable]
        card = {
            "visibility": "partner",
            "referral": referral_obj.to_dict(),
            "patient": {"id": patient.id, "patient_ref": patient.patient_ref,
                        "home_clinic_id": patient.home_clinic_id,
                        "home_clinic_name": self.network.clinics[patient.home_clinic_id]["name"],
                        "status": patient.status},
            "anamnesis": [self._entry_dict(a) for a in shared],
        }
        if referral_obj.status in {"accepted", "completed"}:
            card["patient"].update({"full_name": patient.full_name, "birth_date": patient.birth_date,
                                    "sex": patient.sex, "contact": patient.contact})
        return card

    @staticmethod
    def _entry_dict(entry: AnamnesisEntry) -> dict:
        return {"id": entry.id, "kind": entry.kind, "code": entry.code, "text": entry.text,
                "recorded_at": entry.recorded_at, "author_role": entry.author_role,
                "clinic_id": entry.clinic_id, "version": entry.version, "shareable": entry.shareable}

    # ---------- staff queue / metrics ----------

    def queue(self, clinic_id: str) -> list[dict]:
        with self._lock:
            cases = []
            proposed_to_me = self.db.execute(
                "SELECT r.*, p.patient_ref FROM referrals r JOIN patients p ON p.id=r.patient_id "
                "WHERE r.to_clinic_id=? AND r.status='proposed' ORDER BY r.created_at",
                (clinic_id,)).fetchall()
            for row in proposed_to_me:
                cases.append({"kind": "incoming_referral", "referral_id": row["id"],
                              "patient_id": row["patient_id"], "patient_ref": row["patient_ref"],
                              "from_clinic_id": row["from_clinic_id"], "reason": row["reason"],
                              "created_at": row["created_at"]})
            accepted = self.db.execute(
                "SELECT r.*, p.patient_ref FROM referrals r JOIN patients p ON p.id=r.patient_id "
                "WHERE r.from_clinic_id=? AND r.status='accepted' ORDER BY r.created_at",
                (clinic_id,)).fetchall()
            for row in accepted:
                cases.append({"kind": "awaiting_completion", "referral_id": row["id"],
                              "patient_id": row["patient_id"], "patient_ref": row["patient_ref"],
                              "to_clinic_id": row["to_clinic_id"], "created_at": row["created_at"]})
            return cases

    def metrics(self, clinic_id: str) -> dict:
        with self._lock:
            total = self.db.execute("SELECT COUNT(*) AS n FROM patients WHERE home_clinic_id=?", (clinic_id,)).fetchone()["n"]
            by_status = {row["status"]: row["n"] for row in self.db.execute(
                "SELECT status, COUNT(*) AS n FROM patients WHERE home_clinic_id=? GROUP BY status", (clinic_id,))}
            outgoing = self.db.execute("SELECT COUNT(*) AS n FROM referrals WHERE from_clinic_id=?", (clinic_id,)).fetchone()["n"]
            incoming = self.db.execute("SELECT COUNT(*) AS n FROM referrals WHERE to_clinic_id=?", (clinic_id,)).fetchone()["n"]
            accepted_out = self.db.execute(
                "SELECT COUNT(*) AS n FROM referrals WHERE from_clinic_id=? AND status IN ('accepted','completed')",
                (clinic_id,)).fetchone()["n"]
            anamnesis_n = self.db.execute(
                "SELECT COUNT(*) AS n FROM anamnesis a JOIN patients p ON p.id=a.patient_id WHERE p.home_clinic_id=?",
                (clinic_id,)).fetchone()["n"]
            return {"clinic_id": clinic_id, "patients_total": total, "patients_by_status": by_status,
                    "referrals_outgoing": outgoing, "referrals_incoming": incoming,
                    "referrals_outgoing_accepted": accepted_out,
                    "anamnesis_entries": anamnesis_n,
                    "network_version": self.network.version}