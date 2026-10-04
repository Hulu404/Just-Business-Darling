"""Loopback HTTP API for prescription-driven medication ordering."""
from __future__ import annotations

import hmac
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from auth import verify
from catalog import Catalog, CatalogError
from store import ConflictError, MedError, MedStore
from ui import PATIENT, STAFF

MAX_BODY = 32 * 1024


def make_handler(store: MedStore, shared_secret: str, admin_token: str,
                 patient_token_secret: str, staff_tokens: dict[str, str]):
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

        def _bearer(self, expected: str) -> bool:
            if not expected:
                return False
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + expected)

        def _admin(self) -> bool:
            return self._bearer(admin_token)

        def _staff(self) -> str | None:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return None
            value = header[7:]
            for token, name in staff_tokens.items():
                if hmac.compare_digest(value, token):
                    return name
            return None

        def _signed(self, raw: bytes) -> bool:
            return verify(shared_secret, self.headers.get("X-Path-Timestamp", ""),
                          self.headers.get("X-Path-Signature", ""), raw)

        def _body(self) -> tuple[bytes, dict]:
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise MedError("Content-Type must be application/json")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise MedError("Content-Length is required") from None
            if not 0 < length <= MAX_BODY:
                raise MedError(f"Body must be 1-{MAX_BODY} bytes")
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except (UnicodeDecodeError, ValueError):
                raise MedError("Invalid JSON") from None
            if not isinstance(body, dict):
                raise MedError("Expected JSON object")
            return raw, body

        def _patient_ref_or_none(self) -> str | None:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer ") or not patient_token_secret:
                return None
            value = header[7:]
            with store._lock:
                refs = [r["patient_ref"] for r in store.db.execute("SELECT DISTINCT patient_ref FROM prescriptions")]
            for ref in refs:
                expected = hmac.new(patient_token_secret.encode(), ref.encode(), hashlib.sha256).hexdigest()
                if hmac.compare_digest(value, expected):
                    return ref
            return None

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            parts = path.strip("/").split("/")
            try:
                raw, body = self._body()
            except MedError as exc:
                self._json(400, {"error": str(exc)})
                return

            if path == "/v1/prescriptions" and self._signed(raw):
                try:
                    prescription, duplicate = store.ingest_prescription(body)
                    self._json(200 if duplicate else 201,
                               {"prescription_id": prescription.id, "duplicate": duplicate,
                                "patient_ref": prescription.patient_ref, "items": len(prescription.items)})
                except ConflictError as exc:
                    self._json(409, {"error": str(exc)})
                except MedError as exc:
                    self._json(400, {"error": str(exc)})
                return

            staff = self._staff()
            if staff:
                try:
                    if len(parts) == 4 and parts[:2] == ["v1", "orders"] and parts[3] in {"confirm", "ready", "picked_up", "cancel", "fail"}:
                        if set(body) - {"note"}:
                            raise MedError("Invalid order action fields")
                        order = store.transition_order(parts[2], parts[3], staff, body.get("note"))
                        self._json(200, order.to_dict())
                        return
                except ConflictError as exc:
                    self._json(409, {"error": str(exc)})
                    return
                except MedError as exc:
                    self._json(400, {"error": str(exc)})
                    return

            if self._admin():
                try:
                    if path == "/v1/prescriptions":
                        pid = body.get("prescription_id")
                        if not pid:
                            raise MedError("prescription_id required")
                        result = store.match_offers(pid)
                        self._json(200, result)
                        return
                    if path == "/v1/orders":
                        required = {"prescription_id", "patient_ref", "pharmacy_id", "items"}
                        if set(body) != required:
                            raise MedError("Invalid order fields")
                        order = store.place_order(body["prescription_id"], body["patient_ref"],
                                                   body["pharmacy_id"], body["items"])
                        self._json(201, order.to_dict())
                        return
                except ConflictError as exc:
                    self._json(409, {"error": str(exc)})
                    return
                except MedError as exc:
                    self._json(400, {"error": str(exc)})
                    return

            patient_ref = self._patient_ref_or_none()
            if patient_ref:
                try:
                    if path == "/v1/orders":
                        required = {"prescription_id", "pharmacy_id", "items"}
                        if set(body) != required:
                            raise MedError("Invalid order fields")
                        order = store.place_order(body["prescription_id"], patient_ref,
                                                   body["pharmacy_id"], body["items"])
                        self._json(201, order.to_dict())
                        return
                    if len(parts) == 4 and parts[:2] == ["v1", "orders"] and parts[3] == "cancel":
                        order = store.get_order(parts[2])
                        if not order or order.patient_ref != patient_ref:
                            self._json(404, {"error": "Not found"})
                            return
                        order = store.transition_order(parts[2], "cancel", patient_ref, body.get("note"))
                        self._json(200, order.to_dict())
                        return
                except ConflictError as exc:
                    self._json(409, {"error": str(exc)})
                    return
                except MedError as exc:
                    self._json(400, {"error": str(exc)})
                    return

            self._json(403, {"error": "Authorization required"})

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/patient":
                self._html(PATIENT)
                return
            if path == "/staff":
                self._html(STAFF)
                return
            if path == "/health":
                self._json(200, {"status": "ok", "catalog_version": store.catalog.version,
                                 "inventory_version": store.inventory_version})
                return

            patient_ref = self._patient_ref_or_none()
            if patient_ref:
                if path == "/v1/offers":
                    prescriptions = store.list_prescriptions(patient_ref)
                    self._json(200, {"prescriptions": [p.to_dict() for p in prescriptions]})
                    return
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["v1", "prescriptions"] and parts[3] == "offers":
                    p = store.get_prescription(parts[2])
                    if not p or p.patient_ref != patient_ref:
                        self._json(404, {"error": "Not found"})
                        return
                    self._json(200, store.match_offers(parts[2]))
                    return
                if path == "/v1/orders":
                    self._json(200, {"orders": [o.to_dict() for o in store.list_orders(patient_ref=patient_ref)]})
                    return
                if len(parts) == 3 and parts[:2] == ["v1", "orders"]:
                    o = store.get_order(parts[2])
                    if not o or o.patient_ref != patient_ref:
                        self._json(404, {"error": "Not found"})
                        return
                    self._json(200, o.to_dict())
                    return
                self._json(404, {"error": "Not found"})
                return

            if not (self._staff() or self._admin()):
                self._json(403, {"error": "Authorization required"})
                return

            if path == "/v1/staff/queue":
                self._json(200, {"cases": store.staff_queue()})
                return
            if path == "/v1/staff/metrics":
                self._json(200, store.metrics())
                return
            if path == "/v1/staff/catalog":
                self._json(200, {"version": store.catalog.version,
                                 "pharmacies": [p.__dict__ for p in store.catalog.pharmacies.values()],
                                 "medications": [m.__dict__ for m in store.catalog.medications.values()]})
                return
            if path == "/v1/staff/pharmacies":
                self._json(200, {"pharmacies": [p.__dict__ for p in store.catalog.pharmacies.values()]})
                return
            if path == "/v1/staff/inventory":
                self._json(200, {"inventory": store.inventory})
                return
            self._json(404, {"error": "Not found"})

    return Handler


if __name__ == "__main__":
    shared_secret = os.environ.get("MED_SHARED_SECRET", "")
    admin_token = os.environ.get("MED_ADMIN_TOKEN", "")
    if len(shared_secret) < 16 or len(admin_token) < 16:
        raise SystemExit("MED_SHARED_SECRET and MED_ADMIN_TOKEN must each have at least 16 characters")
    patient_token_secret = os.environ.get("MED_PATIENT_TOKEN", "")
    try:
        staff_tokens = json.loads(os.environ.get("MED_STAFF_TOKENS", "{}"))
    except ValueError:
        raise SystemExit("MED_STAFF_TOKENS must be a JSON object")
    if not isinstance(staff_tokens, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in staff_tokens.items()):
        raise SystemExit("MED_STAFF_TOKENS must map token -> staff name")
    db_path = Path(os.environ.get("MED_DB", str(Path(__file__).with_name("medications.sqlite3"))))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path = Path(os.environ.get("MED_CATALOG", str(Path(__file__).with_name("catalog.json"))))
    inventory_path = Path(os.environ.get("MED_INVENTORY", str(Path(__file__).with_name("pharmacies.json"))))
    store = MedStore(db_path, Catalog(catalog_path), inventory_path)
    server = ThreadingHTTPServer(("127.0.0.1", 8767), make_handler(
        store, shared_secret, admin_token, patient_token_secret, staff_tokens))
    print("Medications marketplace API: http://127.0.0.1:8767")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        store.close()