"""Loopback HTTP API for clinic patient cards, anamnesis, referrals, routing."""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from auth import verify
from network import ClinicNetwork
from store import ClinicError, ClinicStore, ConflictError
from ui import STAFF

MAX_BODY = 32 * 1024


def make_handler(store: ClinicStore, shared_secret: str, admin_token: str,
                 staff_tokens: dict[str, str], mis_token: str = ""):
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
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _bearer(self, token: str) -> bool:
            if not token:
                return False
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def _staff(self) -> str | None:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return None
            value = header[7:]
            for token, clinic_id in staff_tokens.items():
                if hmac.compare_digest(value, token):
                    return clinic_id
            return None

        def _admin(self) -> bool:
            return self._bearer(admin_token)

        def _signed(self, raw: bytes) -> bool:
            return verify(shared_secret, self.headers.get("X-Path-Timestamp", ""),
                          self.headers.get("X-Path-Signature", ""), raw)

        def _body(self) -> tuple[bytes, dict]:
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise ClinicError("Content-Type must be application/json")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise ClinicError("Content-Length is required") from None
            if not 0 < length <= MAX_BODY:
                raise ClinicError(f"Body must be 1-{MAX_BODY} bytes")
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except (UnicodeDecodeError, ValueError):
                raise ClinicError("Invalid JSON") from None
            if not isinstance(body, dict):
                raise ClinicError("Expected JSON object")
            return raw, body

        # ---------- POST ----------

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            parts = path.strip("/").split("/")
            try:
                raw, body = self._body()
            except ClinicError as exc:
                self._json(400, {"error": str(exc)})
                return

            # Signed endpoints for path service
            if path == "/v1/route-candidates" and self._signed(raw):
                try:
                    if set(body) != {"patient_ref", "scope"}:
                        raise ClinicError("Invalid route-candidates fields")
                    result = store.route_candidates(body["patient_ref"], body["scope"])
                    self._json(200, result)
                except ClinicError as exc:
                    self._json(400, {"error": str(exc)})
                return

            if path == "/v1/referrals" and self._signed(raw):
                try:
                    required = {"patient_ref", "from_clinic_id", "to_clinic_id", "reason", "created_by"}
                    if set(body) != required:
                        raise ClinicError("Invalid referral fields")
                    patient = store.get_patient_by_ref(body["patient_ref"])
                    if not patient:
                        self._json(404, {"error": "Patient not found for patient_ref"})
                        return
                    referral = store.create_referral(patient.id, body["from_clinic_id"],
                                                     body["to_clinic_id"], body["reason"], body["created_by"])
                    self._json(201, referral.to_dict())
                except ConflictError as exc:
                    self._json(409, {"error": str(exc)})
                except ClinicError as exc:
                    self._json(400, {"error": str(exc)})
                return

            # Staff / MIS endpoints
            clinic_id = self._staff()
            is_admin = self._admin()
            is_mis = self._bearer(mis_token)
            if not (clinic_id or is_admin or is_mis):
                self._json(403, {"error": "Authorization required"})
                return

            try:
                if path == "/v1/patients":
                    if not (clinic_id or is_mis):
                        raise ClinicError("Only clinic staff or MIS can register patients")
                    if set(body) != {"home_clinic_id", "patient_ref", "full_name",
                                     "birth_date", "sex", "contact"}:
                        raise ClinicError("Invalid patient fields")
                    if clinic_id and body["home_clinic_id"] != clinic_id:
                        self._json(403, {"error": "Staff can register only own clinic patients"})
                        return
                    payload = {k: v for k, v in body.items() if k != "home_clinic_id"}
                    patient = store.create_patient(body["home_clinic_id"], payload)
                    self._json(201, {"patient": patient.__dict__})
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "patients"] and parts[3] == "anamnesis":
                    if not (clinic_id or is_mis):
                        raise ClinicError("Only clinic staff or MIS can append anamnesis")
                    if set(body) != {"kind", "code", "text", "shareable", "recorded_at",
                                     "author_id", "author_role", "clinic_id"}:
                        raise ClinicError("Invalid anamnesis fields")
                    actor_clinic = body["clinic_id"]
                    if clinic_id and actor_clinic != clinic_id:
                        self._json(403, {"error": "Staff can append only to own clinic"})
                        return
                    entry = store.add_anamnesis(parts[2], actor_clinic, body["author_id"],
                                                body["author_role"], {k: body[k] for k in
                                                                      ("kind", "code", "text", "shareable", "recorded_at")})
                    self._json(201, {"entry": entry.__dict__})
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "patients"] and parts[3] == "status":
                    if not clinic_id:
                        raise ClinicError("Only clinic staff can change patient status")
                    if set(body) != {"status", "actor"}:
                        raise ClinicError("Invalid status fields")
                    patient = store.set_patient_status(parts[2], clinic_id, body["status"], body["actor"])
                    self._json(200, {"patient": patient.__dict__})
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "referrals"] and parts[3] in {"accept", "reject", "cancel", "complete"}:
                    if not clinic_id:
                        raise ClinicError("Only clinic staff can act on referrals")
                    if set(body) - {"actor", "note"} or "actor" not in body:
                        raise ClinicError("Invalid referral action fields")
                    referral = store.referral_action(parts[2], parts[3], clinic_id, body["actor"], body.get("note"))
                    self._json(200, referral.to_dict())
                    return
            except ConflictError as exc:
                self._json(409, {"error": str(exc)})
                return
            except ClinicError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(404, {"error": "Not found"})

        # ---------- GET ----------

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/staff":
                self._html(STAFF)
                return
            if path == "/health":
                self._json(200, {"status": "ok", "network_version": store.network.version})
                return
            query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}

            # Signed read for path service
            if path.startswith("/v1/patients/by-ref/"):
                patient_ref = path[len("/v1/patients/by-ref/"):]
                timestamp = self.headers.get("X-Path-Timestamp", "")
                signature = self.headers.get("X-Path-Signature", "")
                # GET signature is over the empty body, path is bearer-verified separately
                if not self._signed(b""):
                    self._json(403, {"error": "Invalid interservice signature"})
                    return
                patient = store.get_patient_by_ref(patient_ref)
                if not patient:
                    self._json(404, {"error": "Not found"})
                    return
                home = store.network.clinics[patient.home_clinic_id]
                self._json(200, {"patient_ref": patient.patient_ref, "home_clinic_id": patient.home_clinic_id,
                                 "home_clinic_name": home["name"], "status": patient.status})
                return

            clinic_id = self._staff()
            is_admin = self._admin()
            if not (clinic_id or is_admin):
                self._json(403, {"error": "Authorization required"})
                return

            if path == "/v1/clinics":
                items = [dict(c) for c in store.network.clinics.values() if c["active"]]
                if clinic_id:
                    visible = {clinic_id, *store.network.partners_of(clinic_id)}
                    items = [c for c in items if c["id"] in visible]
                self._json(200, {"clinics": items, "network_version": store.network.version})
                return
            if path == "/v1/partnerships":
                if not clinic_id:
                    self._json(400, {"error": "Clinic scope required"})
                    return
                self._json(200, {"partners": store.network.partners_of(clinic_id)})
                return
            if path == "/v1/patients":
                scope = clinic_id if clinic_id else query.get("clinic_id")
                if not scope and not is_admin:
                    self._json(400, {"error": "clinic_id is required"})
                    return
                limit = int(query.get("limit", "100"))
                status = query.get("status")
                items = store.list_patients(scope, status=status, limit=limit)
                self._json(200, {"patients": [p.__dict__ for p in items]})
                return
            if path == "/v1/staff/queue":
                if not clinic_id:
                    self._json(400, {"error": "Clinic scope required"})
                    return
                self._json(200, {"cases": store.queue(clinic_id)})
                return
            if path == "/v1/staff/metrics":
                if not clinic_id:
                    self._json(400, {"error": "Clinic scope required"})
                    return
                self._json(200, store.metrics(clinic_id))
                return
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["v1", "patients"] and parts[3] == "card":
                viewer = clinic_id if clinic_id else query.get("clinic_id")
                if not viewer:
                    self._json(400, {"error": "clinic_id is required"})
                    return
                card = store.patient_card(parts[2], viewer)
                if card is None:
                    self._json(404, {"error": "Not visible to this clinic"})
                    return
                self._json(200, card)
                return
            if len(parts) == 3 and parts[:2] == ["v1", "patients"]:
                viewer = clinic_id if clinic_id else query.get("clinic_id")
                if not viewer:
                    self._json(400, {"error": "clinic_id is required"})
                    return
                card = store.patient_card(parts[2], viewer)
                if card is None:
                    self._json(404, {"error": "Not visible to this clinic"})
                    return
                self._json(200, card)
                return
            self._json(404, {"error": "Not found"})

    return Handler


if __name__ == "__main__":
    shared_secret = os.environ.get("CLINIC_SHARED_SECRET", "")
    admin_token = os.environ.get("CLINIC_ADMIN_TOKEN", "")
    if len(shared_secret) < 16 or len(admin_token) < 16:
        raise SystemExit("CLINIC_SHARED_SECRET and CLINIC_ADMIN_TOKEN must each have at least 16 characters")
    try:
        staff_tokens = json.loads(os.environ.get("CLINIC_STAFF_TOKENS", "{}"))
    except ValueError:
        raise SystemExit("CLINIC_STAFF_TOKENS must be a JSON object")
    if not isinstance(staff_tokens, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in staff_tokens.items()):
        raise SystemExit("CLINIC_STAFF_TOKENS must map token -> clinic_id")
    db_path = Path(os.environ.get("CLINIC_DB", str(Path(__file__).with_name("clinic.sqlite3"))))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    network_path = Path(os.environ.get("CLINIC_NETWORK", str(Path(__file__).with_name("network.json"))))
    store = ClinicStore(db_path, ClinicNetwork(network_path))
    server = ThreadingHTTPServer(("127.0.0.1", 8764), make_handler(
        store, shared_secret, admin_token, staff_tokens, os.environ.get("CLINIC_MIS_TOKEN", "")))
    print("Clinic patient-card API: http://127.0.0.1:8764")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        store.close()