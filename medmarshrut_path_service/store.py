"""SQLite repository for episodes, source reports, plan steps and audit events."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from domain import AuditEvent, Episode, PlanStep, SourceReport
from rules import Ruleset, STEP_KINDS


class PathError(ValueError):
    pass


class ConflictError(PathError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_report(report: dict) -> None:
    required = {"source_service", "source_report_id", "source_report_version", "study_type",
                "study_uid", "patient_ref", "anatomy", "protocol_name", "finding_code",
                "conclusion", "confidence", "source_model", "physician_id", "confirmed_at", "confirmation_status"}
    if not isinstance(report, dict) or set(report) != required:
        raise PathError("Invalid source report fields")
    if report["source_service"] != "medmarshrut_image_service" or report["confirmation_status"] != "confirmed":
        raise PathError("Only physician-confirmed image reports are accepted")
    for key in ("source_report_id", "study_type", "study_uid", "finding_code", "conclusion",
                "source_model", "physician_id"):
        value = report[key]
        if not isinstance(value, str) or not value.strip() or len(value) > (4000 if key == "conclusion" else 256):
            raise PathError(f"Invalid {key}")
    for key in ("anatomy", "protocol_name"):
        if not isinstance(report[key], str) or len(report[key]) > 256:
            raise PathError(f"Invalid {key}")
    patient_ref = report["patient_ref"]
    if patient_ref is not None and (not isinstance(patient_ref, str) or not patient_ref.strip() or len(patient_ref) > 128):
        raise PathError("Invalid patient_ref")
    if type(report["source_report_version"]) is not int or report["source_report_version"] < 1:
        raise PathError("Invalid source report version")
    score = report["confidence"]
    if score is not None and (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
        raise PathError("Invalid confidence")
    try:
        confirmed = datetime.fromisoformat(report["confirmed_at"])
    except (TypeError, ValueError):
        raise PathError("Invalid confirmation time") from None
    if confirmed.tzinfo is None:
        raise PathError("Confirmation time needs a time zone")


class EpisodeStore:
    def __init__(self, db_path: Path, rules: Ruleset):
        self.rules = rules
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS source_reports (
                id TEXT PRIMARY KEY, source_service TEXT NOT NULL, source_report_id TEXT NOT NULL,
                source_report_version INTEGER NOT NULL, payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
                UNIQUE(source_service, source_report_id, source_report_version));
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL UNIQUE REFERENCES source_reports(id),
                status TEXT NOT NULL, rule_version TEXT, manual_reason TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT);
            CREATE TABLE IF NOT EXISTS plan_steps (
                id TEXT PRIMARY KEY, episode_id TEXT NOT NULL REFERENCES episodes(id), position INTEGER NOT NULL,
                kind TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL, completed_at TEXT);
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT NOT NULL REFERENCES episodes(id),
                event_type TEXT NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL, details_json TEXT NOT NULL);
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(plan_steps)")}
        for name, definition in {
            "owner": "TEXT NOT NULL DEFAULT 'coordinator'",
            "due_at": "TEXT",
            "continue_on": "TEXT NOT NULL DEFAULT 'confirmed_outcome'",
            "decision_source": "TEXT NOT NULL DEFAULT ''",
            "cycle": "INTEGER NOT NULL DEFAULT 1",
            "appointment_at": "TEXT",
            "stop_reason": "TEXT",
        }.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE plan_steps ADD COLUMN {name} {definition}")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS incoming_outcomes (
                source TEXT NOT NULL, event_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                episode_id TEXT NOT NULL, PRIMARY KEY(source,event_id));
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT NOT NULL,
                event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
        """)

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def _event(self, episode_id: str, event_type: str, actor: str, details: dict) -> None:
        self.db.execute("INSERT INTO audit_events(episode_id,event_type,actor,occurred_at,details_json) VALUES(?,?,?,?,?)",
                        (episode_id, event_type, actor, now(), json.dumps(details, ensure_ascii=False, sort_keys=True)))

    def _outbox(self, episode_id: str, event_type: str, details: dict) -> None:
        self.db.execute("INSERT INTO outbox(episode_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                        (episode_id, event_type, json.dumps(details, ensure_ascii=False), now()))

    def ingest(self, report: dict) -> tuple[Episode, bool]:
        validate_report(report)
        payload = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._lock, self.db:
            existing = self.db.execute("SELECT id,payload_sha256 FROM source_reports WHERE source_service=? AND source_report_id=? AND source_report_version=?",
                (report["source_service"], report["source_report_id"], report["source_report_version"])).fetchone()
            if existing:
                if existing["payload_sha256"] != digest:
                    raise ConflictError("Same source report version has different content")
                episode_id = self.db.execute("SELECT id FROM episodes WHERE source_id=?", (existing["id"],)).fetchone()["id"]
                return self.get(episode_id), True
            prior = self.db.execute("SELECT e.id FROM episodes e JOIN source_reports s ON e.source_id=s.id "
                "WHERE s.source_service=? AND s.source_report_id=? ORDER BY s.source_report_version DESC LIMIT 1",
                (report["source_service"], report["source_report_id"])).fetchone()
            source_id, episode_id = uuid.uuid4().hex, uuid.uuid4().hex
            steps, manual_reason = self.rules.plan(report)
            if prior:
                steps, manual_reason = [], "report_revision"
            if manual_reason:
                steps = [{"kind": "manual_review", "description": f"Review source report: {manual_reason}"}]
            stamp = now()
            self.db.execute("INSERT INTO source_reports VALUES(?,?,?,?,?,?)", (source_id, report["source_service"],
                report["source_report_id"], report["source_report_version"], digest, payload))
            self.db.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?)", (episode_id, source_id,
                "manual_review" if manual_reason else "active", self.rules.version, manual_reason, stamp, stamp, None))
            for position, step in enumerate(steps, 1):
                self.db.execute("INSERT INTO plan_steps(id,episode_id,position,kind,description,status,completed_at) VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, episode_id,
                    position, step["kind"], step["description"], "open", None))
            self.db.execute("UPDATE plan_steps SET decision_source=?, owner=? WHERE episode_id=?",
                            (f"rule:{self.rules.version}" if not manual_reason else "source_report", "coordinator", episode_id))
            self._event(episode_id, "episode_created", report["source_service"],
                        {"rule_version": self.rules.version, "manual_reason": manual_reason,
                         "prior_episode_id": prior["id"] if prior else None})
            self._outbox(episode_id, "episode_created", {"status": "manual_review" if manual_reason else "active"})
            return self.get(episode_id), False

    def get(self, episode_id: str) -> Episode | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if not row:
                return None
            source_row = self.db.execute("SELECT * FROM source_reports WHERE id=?", (row["source_id"],)).fetchone()
            source = json.loads(source_row["payload_json"])
            report = SourceReport(id=source_row["id"], **source)
            steps = tuple(PlanStep(**dict(s)) for s in self.db.execute(
                "SELECT * FROM plan_steps WHERE episode_id=? ORDER BY position", (episode_id,)))
            events = tuple(AuditEvent(id=e["id"], episode_id=e["episode_id"], event_type=e["event_type"],
                actor=e["actor"], occurred_at=e["occurred_at"], details=json.loads(e["details_json"]))
                for e in self.db.execute("SELECT * FROM audit_events WHERE episode_id=? ORDER BY id", (episode_id,)))
            return Episode(id=row["id"], status=row["status"], source_report=report, plan_steps=steps,
                audit_events=events, rule_version=row["rule_version"], manual_reason=row["manual_reason"],
                created_at=row["created_at"], updated_at=row["updated_at"], closed_at=row["closed_at"])

    def list_ids(self, limit: int | None = 100) -> list[str]:
        with self._lock:
            query = "SELECT id FROM episodes ORDER BY created_at DESC"
            return [r["id"] for r in self.db.execute(query + (" LIMIT ?" if limit is not None else ""),
                                                        (limit,) if limit is not None else ())]

    def add_manual_plan(self, episode_id: str, actor: str, steps: list[dict]) -> Episode:
        if not isinstance(actor, str) or not actor.strip() or not isinstance(steps, list) or not steps or len(steps) > 50:
            raise PathError("Actor and 1-50 plan steps are required")
        for step in steps:
            if (not isinstance(step, dict) or set(step) != {"kind", "description"} or step["kind"] not in STEP_KINDS
                    or step["kind"] == "manual_review" or not isinstance(step["description"], str)
                    or not step["description"].strip() or len(step["description"]) > 500):
                raise PathError("Invalid manual plan step")
        with self._lock, self.db:
            episode = self.get(episode_id)
            if not episode:
                raise PathError("Episode not found")
            if episode.status != "manual_review":
                raise ConflictError("Episode is not awaiting manual review")
            stamp = now()
            self.db.execute("UPDATE plan_steps SET status='completed',completed_at=? WHERE episode_id=? AND kind='manual_review' AND status='open'", (stamp, episode_id))
            position = len(episode.plan_steps)
            for index, step in enumerate(steps, position + 1):
                self.db.execute("INSERT INTO plan_steps(id,episode_id,position,kind,description,status,completed_at) VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, episode_id,
                    index, step["kind"], step["description"], "open", None))
            self.db.execute("UPDATE plan_steps SET decision_source=?,owner=? WHERE episode_id=? AND position>?",
                            (f"physician:{actor}", "coordinator", episode_id, position))
            self.db.execute("UPDATE episodes SET status='active',updated_at=? WHERE id=?", (stamp, episode_id))
            self._event(episode_id, "manual_plan_approved", actor, {"steps_added": len(steps)})
            self._outbox(episode_id, "plan_updated", {"steps_added": len(steps)})
            return self.get(episode_id)

    def complete_step(self, episode_id: str, step_id: str, actor: str, evidence: str) -> Episode:
        if not isinstance(actor, str) or not actor.strip() or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 1000:
            raise PathError("Actor and evidence are required")
        with self._lock, self.db:
            episode = self.get(episode_id)
            if not episode:
                raise PathError("Episode not found")
            if episode.status != "active":
                raise ConflictError("Episode is not active")
            step = next((s for s in episode.plan_steps if s.id == step_id), None)
            if not step or step.status != "open":
                raise ConflictError("Plan step is absent or already completed")
            if step.kind != "care_coordination":
                raise ConflictError("Clinical steps require a confirmed visit outcome")
            stamp = now()
            self.db.execute("UPDATE plan_steps SET status='completed',completed_at=? WHERE id=?", (stamp, step_id))
            self.db.execute("UPDATE episodes SET updated_at=? WHERE id=?", (stamp, episode_id))
            self._event(episode_id, "step_completed", actor, {"step_id": step_id, "evidence": evidence})
            return self.get(episode_id)

    def close_episode(self, episode_id: str, actor: str, outcome: str) -> Episode:
        if not isinstance(actor, str) or not actor.strip() or not isinstance(outcome, str) or not outcome.strip() or len(outcome) > 1000:
            raise PathError("Actor and outcome are required")
        with self._lock, self.db:
            episode = self.get(episode_id)
            if not episode:
                raise PathError("Episode not found")
            if episode.status != "active" or any(s.status not in {"completed", "superseded"} for s in episode.plan_steps):
                raise ConflictError("Complete all plan steps before closing the active episode")
            stamp = now()
            self.db.execute("UPDATE episodes SET status='completed',updated_at=?,closed_at=? WHERE id=?", (stamp, stamp, episode_id))
            self._event(episode_id, "episode_completed", actor, {"outcome": outcome})
            return self.get(episode_id)

    def stop_episode(self, episode_id: str, actor: str, reason: str) -> Episode:
        if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise PathError("Actor and closure reason required")
        with self._lock, self.db:
            episode = self.get(episode_id)
            if not episode:
                raise PathError("Episode not found")
            if episode.status not in {"paused", "manual_review", "active"}:
                raise ConflictError("Episode already closed")
            stamp = now()
            self.db.execute("UPDATE plan_steps SET status='closed',stop_reason=? WHERE episode_id=? AND status NOT IN ('completed','superseded')",
                            (reason, episode_id))
            self.db.execute("UPDATE episodes SET status='closed',manual_reason=?,updated_at=?,closed_at=? WHERE id=?",
                            (reason, stamp, stamp, episode_id))
            self._event(episode_id, "episode_closed", actor, {"reason": reason})
            self._outbox(episode_id, "episode_closed", {"reason": reason})
            return self.get(episode_id)

    @staticmethod
    def _timestamp(value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            raise PathError("Invalid time") from None
        if parsed.tzinfo is None:
            raise PathError("Time needs a time zone")
        return parsed.isoformat()

    def _step(self, episode_id: str, step_id: str) -> tuple[Episode, PlanStep]:
        episode = self.get(episode_id)
        if not episode:
            raise PathError("Episode not found")
        step = next((s for s in episode.plan_steps if s.id == step_id), None)
        if not step:
            raise PathError("Step not found")
        if episode.status != "active":
            raise ConflictError("Episode is not active")
        return episode, step

    def transition(self, episode_id: str, step_id: str, action: str, actor: str,
                   *, evidence: str, appointment_at: str | None = None,
                   due_at: str | None = None) -> Episode:
        allowed = {"offer": ({"open"}, "offered"), "confirm": ({"offered"}, "confirmed"),
                   "attend": ({"confirmed"}, "attended"), "cancel": ({"offered", "confirmed"}, "cancelled"),
                   "refuse": ({"offered", "confirmed"}, "refused"),
                   "lost_contact": ({"open", "offered", "confirmed"}, "lost_contact")}
        if action not in allowed or not isinstance(actor, str) or not actor.strip() or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 1000:
            raise PathError("Invalid transition, actor or evidence")
        appointment_at = self._timestamp(appointment_at)
        due_at = self._timestamp(due_at)
        if action == "offer" and not appointment_at:
            raise PathError("Offer needs appointment_at")
        with self._lock, self.db:
            episode, step = self._step(episode_id, step_id)
            before, after = allowed[action]
            if step.status not in before or step.kind == "manual_review":
                raise ConflictError(f"Step must be one of {sorted(before)}")
            if action == "offer" and any(s.position < step.position and s.status != "completed" for s in episode.plan_steps):
                raise ConflictError("Earlier plan step is unfinished")
            stamp = now()
            self.db.execute("UPDATE plan_steps SET status=?,appointment_at=COALESCE(?,appointment_at),due_at=COALESCE(?,due_at),stop_reason=? WHERE id=?",
                            (after, appointment_at, due_at, action if action in {"cancel", "refuse", "lost_contact"} else None, step_id))
            if action in {"cancel", "refuse", "lost_contact"}:
                self.db.execute("UPDATE episodes SET status='paused',manual_reason=?,updated_at=? WHERE id=?", (action, stamp, episode_id))
            else:
                self.db.execute("UPDATE episodes SET updated_at=? WHERE id=?", (stamp, episode_id))
            self._event(episode_id, f"step_{after}", actor, {"step_id": step_id, "evidence": evidence,
                "appointment_at": appointment_at, "due_at": due_at})
            self._outbox(episode_id, f"step_{after}", {"step_id": step_id, "appointment_at": appointment_at})
            return self.get(episode_id)

    def confirmed_outcome(self, episode_id: str, step_id: str, payload: dict) -> tuple[Episode, bool]:
        required = {"source", "event_id", "physician_id", "confirmed_at", "summary", "next_steps"}
        if not isinstance(payload, dict) or set(payload) != required or payload["source"] not in {"mis", "staff_form"}:
            raise PathError("Invalid confirmed outcome")
        for key in ("event_id", "physician_id", "summary"):
            if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 1000:
                raise PathError(f"Invalid {key}")
        self._timestamp(payload["confirmed_at"])
        steps = payload["next_steps"]
        if not isinstance(steps, list) or len(steps) > 50:
            raise PathError("Invalid next steps")
        for item in steps:
            if (not isinstance(item, dict) or set(item) != {"kind", "description", "owner", "due_at", "continue_on"}
                    or item["kind"] not in STEP_KINDS - {"manual_review"}
                    or any(not isinstance(item[k], str) or not item[k].strip() or len(item[k]) > 500
                           for k in ("description", "owner", "continue_on"))):
                raise PathError("Invalid next step")
            self._timestamp(item["due_at"])
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._lock, self.db:
            prior = self.db.execute("SELECT * FROM incoming_outcomes WHERE source=? AND event_id=?",
                                    (payload["source"], payload["event_id"])).fetchone()
            if prior:
                if prior["payload_sha256"] != digest or prior["episode_id"] != episode_id:
                    raise ConflictError("Outcome event id reused with different content")
                return self.get(episode_id), True
            episode, step = self._step(episode_id, step_id)
            if step.status != "attended":
                raise ConflictError("Confirmed outcome requires an attended visit")
            stamp = now()
            self.db.execute("UPDATE plan_steps SET status='completed',completed_at=? WHERE id=?", (stamp, step_id))
            for position, item in enumerate(steps, len(episode.plan_steps) + 1):
                self.db.execute("INSERT INTO plan_steps(id,episode_id,position,kind,description,status,completed_at,owner,due_at,continue_on,decision_source,cycle) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, episode_id, position, item["kind"], item["description"], "open", None,
                     item["owner"], self._timestamp(item["due_at"]), item["continue_on"],
                     f"{payload['source']}:{payload['event_id']}:physician:{payload['physician_id']}", step.cycle + 1))
            self.db.execute("INSERT INTO incoming_outcomes VALUES(?,?,?,?)",
                            (payload["source"], payload["event_id"], digest, episode_id))
            self.db.execute("UPDATE episodes SET updated_at=? WHERE id=?", (stamp, episode_id))
            self._event(episode_id, "outcome_confirmed", payload["physician_id"],
                        {"step_id": step_id, "source": payload["source"], "event_id": payload["event_id"],
                         "confirmed_at": payload["confirmed_at"], "summary": payload["summary"], "steps_added": len(steps)})
            self._outbox(episode_id, "plan_updated", {"steps_added": len(steps)})
            return self.get(episode_id), False

    def revise_plan(self, episode_id: str, physician_id: str, reason: str, steps: list[dict]) -> Episode:
        if not physician_id or not reason or not isinstance(steps, list) or not steps:
            raise PathError("Physician, reason and replacement steps required")
        # Reuse outcome validation for the shape of physician-authored steps.
        for item in steps:
            if (not isinstance(item, dict) or set(item) != {"kind", "description", "owner", "due_at", "continue_on"}
                    or item["kind"] not in STEP_KINDS - {"manual_review"} or
                    any(not isinstance(item[k], str) or not item[k].strip() for k in ("description", "owner", "continue_on"))):
                raise PathError("Invalid replacement step")
            self._timestamp(item["due_at"])
        with self._lock, self.db:
            episode = self.get(episode_id)
            if not episode or episode.status not in {"active", "paused"}:
                raise ConflictError("Episode cannot be revised")
            stamp = now()
            self.db.execute("UPDATE plan_steps SET status='superseded',stop_reason='plan_changed' WHERE episode_id=? AND status NOT IN ('completed','superseded')", (episode_id,))
            cycle = max(s.cycle for s in episode.plan_steps) + 1
            for position, item in enumerate(steps, len(episode.plan_steps) + 1):
                self.db.execute("INSERT INTO plan_steps(id,episode_id,position,kind,description,status,completed_at,owner,due_at,continue_on,decision_source,cycle) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, episode_id, position, item["kind"], item["description"], "open", None,
                     item["owner"], item["due_at"], item["continue_on"], f"physician_revision:{physician_id}", cycle))
            self.db.execute("UPDATE episodes SET status='active',manual_reason=NULL,updated_at=? WHERE id=?", (stamp, episode_id))
            self._event(episode_id, "plan_revised", physician_id, {"reason": reason, "steps_added": len(steps)})
            self._outbox(episode_id, "plan_updated", {"steps_added": len(steps)})
            return self.get(episode_id)

    def coordinator_queue(self, at: str | None = None) -> list[dict]:
        at = self._timestamp(at) or now()
        cases = []
        for episode_id in self.list_ids(None):
            episode = self.get(episode_id)
            reasons = []
            if episode.status in {"manual_review", "paused"}:
                reasons.append(episode.manual_reason or episode.status)
            for step in episode.plan_steps:
                if step.status == "attended":
                    reasons.append("awaiting_confirmed_outcome")
                if step.status in {"open", "offered", "confirmed"}:
                    reasons.append("unfinished:" + step.id)
                    if step.due_at and datetime.fromisoformat(step.due_at) < datetime.fromisoformat(at):
                        reasons.append("overdue:" + step.id)
            if reasons:
                cases.append({"episode_id": episode.id, "status": episode.status, "reasons": reasons,
                              "actions": ["request_physician_plan"] if episode.status != "active" else ["contact_owner_or_record_outcome"]})
        return cases

    def patient_view(self, patient_ref: str) -> list[dict]:
        if not patient_ref:
            raise PathError("Patient reference required")
        views = []
        for episode_id in self.list_ids(None):
            episode = self.get(episode_id)
            if episode.source_report.patient_ref == patient_ref:
                current = next((s for s in episode.plan_steps if s.status in {"open", "offered", "confirmed"}), None)
                views.append({"episode_id": episode.id, "status": episode.status,
                              "do_now": {"description": current.description, "status": current.status,
                                         "appointment_at": current.appointment_at} if current and episode.status == "active" else None,
                              "plan_history": [{"description": s.description, "status": s.status, "cycle": s.cycle,
                                                "appointment_at": s.appointment_at} for s in episode.plan_steps]})
        return views

    def metrics(self) -> dict:
        episodes = [self.get(i) for i in self.list_ids(None)]
        steps = [s for e in episodes for s in e.plan_steps if s.kind != "manual_review"]
        events = [a for e in episodes for a in e.audit_events]
        offered = [a for a in events if a.event_type == "step_offered"]
        confirmed = [a for a in events if a.event_type == "step_confirmed"]
        attended = [a for a in events if a.event_type == "step_attended"]
        contacts = []
        for e in episodes:
            first = next((a for a in e.audit_events if a.event_type == "step_offered"), None)
            if first:
                contacts.append((datetime.fromisoformat(first.occurred_at) - datetime.fromisoformat(e.source_report.confirmed_at)).total_seconds())
        route_errors = [e for e in episodes if e.manual_reason in {"unsupported_protocol", "unknown_finding_code", "no_approved_rule", "rule_not_approved", "report_revision"}]
        return {"contact_seconds_average": sum(contacts) / len(contacts) if contacts else None,
                "offered_share": len(offered) / len(steps) if steps else None,
                "confirmed_share_of_offered": len(confirmed) / len(offered) if offered else None,
                "attended_visits": len(attended),
                "unfinished_episodes": sum(e.status != "completed" for e in episodes),
                "manual_correction_share": sum(any(a.event_type in {"manual_plan_approved", "plan_revised"}
                    for a in e.audit_events) for e in episodes) / len(episodes) if episodes else None,
                "route_quality": {"episodes_requiring_route_review": len(route_errors),
                                  "share_requiring_route_review": len(route_errors) / len(episodes) if episodes else None}}

    def outbox(self) -> list[dict]:
        with self._lock:
            return [{"id": r["id"], "episode_id": r["episode_id"], "event_type": r["event_type"],
                     "payload": json.loads(r["payload_json"]), "created_at": r["created_at"]}
                    for r in self.db.execute("SELECT * FROM outbox ORDER BY id")]
