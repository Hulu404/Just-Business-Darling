"""Local DICOM inference and physician review API."""
from __future__ import annotations

import io
import json
import os
import secrets
import zipfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as InferenceTimeout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from dicom_ingest import MAX_ARCHIVE, IntakeError, inspect_archive, parse_manifest
from model import TASKS, LocalONNXBackend, ModelBackend, ModelError, TestBackend


class ReviewError(Exception):
    pass


def _draft(result: dict) -> list[dict]:
    """Each sentence has a direct finding reference; no free-form generation."""
    if result.get("refusal_reason"):
        return []
    lines = []
    for i, finding in enumerate(result["findings"]):
        loc = finding["localization"]
        place = loc.get("projection") or f"срез {loc['slice_index']}"
        lines.append({"finding_id": i, "text":
                      f"Модель предполагает: {finding['description']} ({place}, серия {loc['series_uid']}, "
                      f"экземпляр {loc['sop_uid']}; оценка {finding['confidence']:.2f}). Требуется проверка врача."})
    return lines


def _validate_result(result: dict, study: dict) -> None:
    if result.get("kind") != "model_inference" or not isinstance(result.get("findings"), list):
        raise ModelError("Invalid inference result")
    if not isinstance(result.get("limitations"), list) or not isinstance(result.get("input_quality"), dict):
        raise ModelError("Missing model limitations or input quality")
    for finding in result["findings"]:
        loc = finding.get("localization", {})
        series = study["series"].get(loc.get("series_uid"))
        if (not series or not isinstance(finding.get("description"), str) or not finding["description"]
                or not isinstance(finding.get("code"), str) or not finding["code"]):
            raise ModelError("Invalid finding")
        confidence = finding.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ModelError("Invalid confidence")
        if study["modality"] == "MG":
            if series["projections"].get(loc.get("sop_uid")) != loc.get("projection"):
                raise ModelError("Invalid projection")
        elif (loc.get("sop_uid") not in series["ordered_sop_uids"] or
              loc.get("slice_index") != series["ordered_sop_uids"].index(loc["sop_uid"]) + 1):
            raise ModelError("Invalid slice localization")
        if study["modality"] == "MG" and "BI-RADS" in finding["description"].upper():
            raise ModelError("BI-RADS is unavailable without separate validation")


class StudyService:
    def __init__(self, backend: ModelBackend | None = None, *, timeout_seconds: float = 30,
                 router_url: str | None = None) -> None:
        self.backend = backend
        self.load_error = None
        if backend is not None:
            try:
                backend.load_model()
            except (ModelError, OSError, MemoryError, RuntimeError) as exc:
                self.load_error = f"Model load failed: {exc}"
        self.timeout_seconds = timeout_seconds
        self.router_url = router_url
        if router_url and not router_url.startswith("http://127.0.0.1:"):
            raise ValueError("Router URL must use loopback")
        self._jobs: dict[str, dict] = {}
        self._archives: dict[str, bytes] = {}
        self._lock = Lock()

    def submit(self, archive: bytes, raw_manifest: str) -> dict:
        job_id = secrets.token_urlsafe(18)
        record = {"id": job_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "status": "processing", "reason": None, "study": None, "result": None,
                  "draft": [], "edits": [], "confirmation": None, "routing_status": None}
        with self._lock:
            self._jobs[job_id] = record
        try:
            study = inspect_archive(archive, parse_manifest(raw_manifest))
            record["study"] = study
            with self._lock:
                self._archives[job_id] = archive
            if self.load_error:
                record.update(status="manual_review", reason=self.load_error)
            elif self.backend is None:
                record.update(status="manual_review", reason="No local model backend is configured")
            else:
                task = TASKS[study["task"]]
                compatible, reason = self.backend.check_compatibility(study, task)
                if not compatible:
                    record.update(status="manual_review", reason=reason)
                elif type(self.backend) is TestBackend:
                    record.update(status="test_only", result=self.backend.infer_local(study, task, archive))
                else:
                    pool = ThreadPoolExecutor(max_workers=1)
                    try:
                        future = pool.submit(self.backend.infer_local, study, task, archive)
                        try:
                            result = future.result(timeout=self.timeout_seconds)
                        except InferenceTimeout:
                            raise ModelError("Inference timed out") from None
                    finally:
                        pool.shutdown(wait=False, cancel_futures=True)
                    _validate_result(result, study)
                    if result.get("refusal_reason"):
                        record.update(status="manual_review", reason=result["refusal_reason"], result=result)
                    elif not result["findings"]:
                        record.update(status="manual_review", reason="No supported finding above threshold", result=result)
                    else:
                        record.update(status="awaiting_physician", result=result, draft=_draft(result))
        except IntakeError as exc:
            record.update(status="manual_review", reason=str(exc))
        except MemoryError:
            record.update(status="manual_review", reason="Insufficient memory for inference")
        except (ModelError, RuntimeError, OSError, ValueError) as exc:
            record.update(status="manual_review", reason=f"Inference failed: {exc}")
        except Exception:
            record.update(status="manual_review", reason="Inference failed; inspect local logs")
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def public(self, job_id: str) -> dict | None:
        job = self.get(job_id)
        if job is None:
            return None
        return {key: job[key] for key in ("id", "created_at", "status", "reason", "routing_status")}

    def image(self, job_id: str, sop_uid: str) -> bytes | None:
        with self._lock:
            archive = self._archives.get(job_id)
            study = self._jobs.get(job_id, {}).get("study")
        if archive is None or not study or not any(sop_uid in s.get("ordered_sop_uids", [])
                                                   for s in study["series"].values()) and study["modality"] != "MG":
            return None
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            from pydicom import dcmread
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                data = z.read(name)
                if str(dcmread(io.BytesIO(data), stop_before_pixels=True).SOPInstanceUID) == sop_uid:
                    return data
        return None

    def confirm(self, job_id: str, body: dict) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ReviewError("Study not found")
            if job["status"] != "awaiting_physician":
                raise ReviewError("Study is not awaiting physician confirmation")
            if not isinstance(body, dict) or set(body) != {"physician_id", "conclusion", "edits", "finding_code"}:
                raise ReviewError("Invalid confirmation fields")
            physician = body["physician_id"]
            conclusion = body["conclusion"]
            edits = body["edits"]
            code = body["finding_code"]
            if (not isinstance(physician, str) or not 1 <= len(physician) <= 128
                    or not isinstance(conclusion, str) or not 1 <= len(conclusion) <= 4000
                    or not isinstance(edits, list) or not all(isinstance(x, str) and len(x) <= 1000 for x in edits)
                    or code not in {f["code"] for f in job["result"]["findings"]}):
                raise ReviewError("Invalid physician confirmation or finding code")
            finding = next(f for f in job["result"]["findings"] if f["code"] == code)
            payload = {"study_type": {"CT": "ct", "MG": "mammography"}.get(job["study"]["modality"]),
                       "finding_code": code, "conclusion": conclusion, "confidence": finding["confidence"],
                       "source_report_id": job_id, "source_model": job["result"]["model_version"]}
            job.update(status="confirmed", edits=edits,
                       confirmation={"physician_id": physician, "conclusion": conclusion,
                                     "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                     "routing_payload": payload},
                       routing_status="pending" if self.router_url and payload["study_type"] else "not_configured_or_unsupported")
        if self.router_url and payload["study_type"]:
            try:
                request = Request(self.router_url, data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(request, timeout=5) as response:
                    if not 200 <= response.status < 300:
                        raise OSError("Router rejected report")
                job["routing_status"] = "sent"
            except (OSError, TimeoutError):
                job["routing_status"] = "failed"
        return self.get(job_id)


def make_handler(service: StudyService, reviewer_token: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _json(self, code: int, body: dict) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            return bool(reviewer_token and secrets.compare_digest(self.headers.get("Authorization", ""),
                                                                  "Bearer " + reviewer_token))

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path.startswith("/v1/review/"):
                if not self._authorized():
                    self._json(403, {"error": "Reviewer authorization required"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                    if not 0 < length <= 8192:
                        raise ValueError()
                    body = json.loads(self.rfile.read(length))
                    self._json(200, service.confirm(path.rsplit("/", 1)[1], body))
                except (ValueError, ReviewError) as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path != "/v1/studies":
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
            result = service.submit(self.rfile.read(length), manifest)
            reason = result.get("reason") or ""
            code = (504 if "timed out" in reason else 503 if reason.startswith(("Inference failed", "Model load failed", "Insufficient memory"))
                    else 422 if result["status"] == "manual_review" and reason != "No local model backend is configured"
                    else 202 if result["status"] == "manual_review" else 201)
            self._json(code, service.public(result["id"]))

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/health":
                self._json(200, {"status": "ok"})
                return
            if path.startswith("/v1/review/"):
                if not self._authorized():
                    self._json(403, {"error": "Reviewer authorization required"})
                    return
                parts = path.split("/")
                if len(parts) == 6 and parts[4] == "images":
                    data = service.image(parts[3], parts[5])
                    if data is None:
                        self._json(404, {"error": "Image not found"})
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/dicom")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        self.wfile.write(data)
                    return
                job = service.get(parts[3]) if len(parts) == 4 else None
                self._json(200, job) if job else self._json(404, {"error": "Not found"})
                return
            if not path.startswith("/v1/studies/") or path.count("/") != 3:
                self._json(404, {"error": "Not found"})
                return
            job = service.public(path.rsplit("/", 1)[1])
            self._json(200, job) if job else self._json(404, {"error": "Not found"})

    return Handler


if __name__ == "__main__":
    config = os.environ.get("MODEL_CONFIG")
    backend = LocalONNXBackend(Path(config)) if config else TestBackend() if os.environ.get("ENABLE_TEST_BACKEND") == "1" else None
    token = os.environ.get("REVIEWER_TOKEN")
    if not token:
        raise SystemExit("REVIEWER_TOKEN is required")
    server = ThreadingHTTPServer(("127.0.0.1", 8766), make_handler(
        StudyService(backend, router_url=os.environ.get("ROUTER_URL")), token))
    print("DICOM review API: http://127.0.0.1:8766")
    server.serve_forever()
