"""Loopback HTTP API for physician-confirmed image reports and episodes."""
from __future__ import annotations

import json
import os
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from auth import verify
from rules import Ruleset
from store import ConflictError, EpisodeStore, PathError
from ui import PATIENT, STAFF

MAX_BODY = 16 * 1024


def make_handler(store: EpisodeStore, shared_secret: str, admin_token: str,
                 patient_token: str = "", mis_token: str = ""):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _html(self, page: str) -> None:
            data = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _admin(self) -> bool:
            from hmac import compare_digest
            return bool(admin_token and compare_digest(self.headers.get("Authorization", ""), "Bearer " + admin_token))

        def _token(self, value: str) -> bool:
            from hmac import compare_digest
            return bool(value and compare_digest(self.headers.get("Authorization", ""), "Bearer " + value))

        def _body(self) -> tuple[bytes, dict]:
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise PathError("Content-Type must be application/json")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise PathError("Content-Length is required") from None
            if not 0 < length <= MAX_BODY:
                raise PathError("Body must be 1-16384 bytes")
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except (UnicodeDecodeError, ValueError):
                raise PathError("Invalid JSON") from None
            if not isinstance(body, dict):
                raise PathError("Expected JSON object")
            return raw, body

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path == "/v1/rules/dry-run":
                if not self._admin():
                    self._json(403, {"error": "Administrator authorization required"})
                    return
                try:
                    _, body = self._body()
                    if set(body) != {"study_type", "anatomy", "protocol_name", "finding_code"}:
                        raise PathError("Invalid dry-run fields")
                    if any(not isinstance(value, str) or not value.strip() for value in body.values()):
                        raise PathError("Invalid dry-run values")
                    steps, reason = store.rules.plan({**body, "patient_ref": "dry-run-patient"})
                    self._json(200, {"dry_run": True, "steps": steps,
                                     "manual_reason": reason, "rule_version": store.rules.version})
                except PathError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path in {"/v1/reports", "/v1/episodes"}:
                try:
                    raw, body = self._body()
                    if not verify(shared_secret, self.headers.get("X-Path-Timestamp", ""),
                                  self.headers.get("X-Path-Signature", ""), raw):
                        self._json(403, {"error": "Invalid interservice signature"})
                        return
                    episode, duplicate = store.ingest(body)
                    self._json(200 if duplicate else 201, {"episode_id": episode.id,
                        "status": episode.status, "manual_reason": episode.manual_reason, "duplicate": duplicate})
                except ConflictError as exc:
                    self._json(409, {"error": str(exc)})
                except PathError as exc:
                    self._json(400, {"error": str(exc)})
                return
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["v1", "episodes"] and parts[3] == "outcomes":
                if not (self._admin() or self._token(mis_token)):
                    self._json(403, {"error": "Staff or MIS authorization required"})
                    return
                try:
                    _, body = self._body()
                    if set(body) != {"step_id", "outcome"}:
                        raise PathError("Invalid outcome fields")
                    if body["outcome"].get("source") == "mis" and not self._token(mis_token):
                        self._json(403, {"error": "MIS token required"})
                        return
                    if body["outcome"].get("source") == "staff_form" and not self._admin():
                        self._json(403, {"error": "Staff token required"})
                        return
                    episode, duplicate = store.confirmed_outcome(parts[2], body["step_id"], body["outcome"])
                    self._json(200, {"episode": episode.to_dict(), "duplicate": duplicate})
                except ConflictError as exc:
                    self._json(409, {"error": str(exc)})
                except (PathError, AttributeError, TypeError) as exc:
                    self._json(400, {"error": str(exc)})
                return
            if not self._admin():
                self._json(403, {"error": "Administrator authorization required"})
                return
            if len(parts) < 4 or parts[:2] != ["v1", "episodes"]:
                self._json(404, {"error": "Not found"})
                return
            episode_id = parts[2]
            try:
                _, body = self._body()
                if len(parts) == 4 and parts[3] == "manual-plan":
                    if set(body) != {"actor", "steps"}:
                        raise PathError("Invalid manual plan fields")
                    episode = store.add_manual_plan(episode_id, body["actor"], body["steps"])
                elif len(parts) == 4 and parts[3] == "close":
                    if set(body) != {"actor", "outcome"}:
                        raise PathError("Invalid closure fields")
                    episode = store.close_episode(episode_id, body["actor"], body["outcome"])
                elif len(parts) == 4 and parts[3] == "stop":
                    if set(body) != {"actor", "reason"}:
                        raise PathError("Invalid stop fields")
                    episode = store.stop_episode(episode_id, body["actor"], body["reason"])
                elif len(parts) == 5 and parts[3] == "steps" and parts[4]:
                    if set(body) != {"actor", "evidence"}:
                        raise PathError("Invalid step completion fields")
                    episode = store.complete_step(episode_id, parts[4], body["actor"], body["evidence"])
                elif len(parts) == 6 and parts[3] == "steps" and parts[5] in {"offer", "confirm", "attend", "cancel", "refuse", "lost_contact"}:
                    if not {"actor", "evidence"} <= set(body) or set(body) - {"actor", "evidence", "appointment_at", "due_at"}:
                        raise PathError("Invalid transition fields")
                    episode = store.transition(episode_id, parts[4], parts[5], body["actor"],
                        evidence=body["evidence"], appointment_at=body.get("appointment_at"), due_at=body.get("due_at"))
                elif len(parts) == 4 and parts[3] == "revise-plan":
                    if set(body) != {"physician_id", "reason", "steps"}:
                        raise PathError("Invalid plan revision fields")
                    episode = store.revise_plan(episode_id, body["physician_id"], body["reason"], body["steps"])
                else:
                    self._json(404, {"error": "Not found"})
                    return
                self._json(200, episode.to_dict())
            except ConflictError as exc:
                self._json(409, {"error": str(exc)})
            except PathError as exc:
                self._json(400, {"error": str(exc)})

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/patient":
                self._html(PATIENT)
                return
            if path == "/staff":
                self._html(STAFF)
                return
            if path == "/health":
                self._json(200, {"status": "ok"})
                return
            if path.startswith("/v1/patient/"):
                patient_ref = path.removeprefix("/v1/patient/")
                expected = hmac.new(patient_token.encode(), patient_ref.encode(), hashlib.sha256).hexdigest() if patient_token else ""
                if not expected or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + expected):
                    self._json(403, {"error": "Patient authorization required"})
                    return
                self._json(200, {"episodes": store.patient_view(patient_ref)})
                return
            if not self._admin():
                self._json(403, {"error": "Administrator authorization required"})
                return
            if path == "/v1/episodes":
                self._json(200, {"episode_ids": store.list_ids()})
                return
            if path == "/v1/rules":
                self._json(200, {"version": store.rules.version,
                                 "supported_protocols": [dict(zip(("study_type", "anatomy", "protocol_name"), scope))
                                                         for scope in sorted(store.rules.scopes)],
                                 "rules": list(store.rules.rules.values())})
                return
            if path == "/v1/staff/queue":
                self._json(200, {"cases": store.coordinator_queue()})
                return
            if path == "/v1/staff/metrics":
                self._json(200, store.metrics())
                return
            if path == "/v1/staff/outbox":
                self._json(200, {"events": store.outbox()})
                return
            parts = path.strip("/").split("/")
            if len(parts) != 3 or parts[:2] != ["v1", "episodes"]:
                self._json(404, {"error": "Not found"})
                return
            episode = store.get(parts[2])
            self._json(200, episode.to_dict()) if episode else self._json(404, {"error": "Not found"})

    return Handler


if __name__ == "__main__":
    shared_secret = os.environ.get("PATH_SHARED_SECRET", "")
    admin_token = os.environ.get("PATH_ADMIN_TOKEN", "")
    if len(shared_secret) < 16 or len(admin_token) < 16:
        raise SystemExit("PATH_SHARED_SECRET and PATH_ADMIN_TOKEN must each have at least 16 characters")
    db_path = Path(os.environ.get("PATH_DB", str(Path(__file__).with_name("path.sqlite3"))))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path = Path(os.environ.get("PATH_RULES", str(Path(__file__).with_name("rules.json"))))
    store = EpisodeStore(db_path, Ruleset(rules_path))
    server = ThreadingHTTPServer(("127.0.0.1", 8765), make_handler(store, shared_secret, admin_token,
        os.environ.get("PATH_PATIENT_TOKEN", ""), os.environ.get("PATH_MIS_TOKEN", "")))
    print("Patient pathway API: http://127.0.0.1:8765")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        store.close()
