"""Standalone local DICOM intake service. No network clients or clinical inference."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit

from dicom_ingest import MAX_ARCHIVE, IntakeError, inspect_archive, parse_manifest
from model import TASKS, ModelBackend, TestBackend


class StudyService:
    def __init__(self, backend: ModelBackend | None = None) -> None:
        if backend is not None and type(backend) is not TestBackend:
            raise ValueError("Only the explicitly marked TestBackend is enabled")
        self.backend = backend
        if backend is not None:
            backend.load_model()
        self._jobs: dict[str, dict] = {}
        self._lock = Lock()

    def submit(self, archive: bytes, raw_manifest: str) -> dict:
        job_id = secrets.token_urlsafe(18)
        record = {"id": job_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "status": "processing", "reason": None, "study": None, "result": None}
        with self._lock:
            self._jobs[job_id] = record
        try:
            manifest = parse_manifest(raw_manifest)
            study = inspect_archive(archive, manifest)
            record["study"] = study
            if self.backend is None:
                record.update(status="manual_review", reason="No local model backend is configured")
            else:
                compatible, reason = self.backend.check_compatibility(study, TASKS[study["task"]])
                if not compatible:
                    record.update(status="manual_review", reason=reason)
                else:
                    result = self.backend.infer_local(study, TASKS[study["task"]])
                    record.update(status="test_only", result=result)
        except IntakeError as exc:
            record.update(status="manual_review", reason=str(exc))
        except Exception:
            record.update(status="manual_review", reason="Internal processing error; inspect locally")
        return dict(record)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


def make_handler(service: StudyService):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            # Default HTTP logging includes request path and user controlled text.
            return

        def _json(self, code: int, body: dict) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/v1/studies":
                self._json(404, {"error": "Not found"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/zip":
                self._json(415, {"error": "Content-Type must be application/zip"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if not 0 < length <= MAX_ARCHIVE:
                self._json(413, {"error": "Archive must be 1–50 MiB and have Content-Length"})
                return
            manifest = self.headers.get("X-Study-Manifest", "")
            if len(manifest) > 65536:
                self._json(413, {"error": "Manifest exceeds 64 KiB"})
                return
            archive = self.rfile.read(length)
            self._json(201, service.submit(archive, manifest))

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/health":
                self._json(200, {"status": "ok"})
                return
            if not path.startswith("/v1/studies/") or path.count("/") != 3:
                self._json(404, {"error": "Not found"})
                return
            job = service.get(path.rsplit("/", 1)[1])
            self._json(200, job) if job else self._json(404, {"error": "Not found"})

    return Handler



if __name__ == "__main__":
    backend = TestBackend() if os.environ.get("ENABLE_TEST_BACKEND") == "1" else None
    server = ThreadingHTTPServer(("127.0.0.1", 8766), make_handler(StudyService(backend)))
    print("DICOM intake: http://127.0.0.1:8766 (local only)")
    server.serve_forever()
