"""Task 05: manifest, PNG preview, study routes, access and leaks. No database: the registry is faked here,
the PostgreSQL part lives in test_study_registry.py."""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from errors import GatewayError
from imaging import EDITED, build_manifest, dicom_to_png
from test_gateway import GatewayTestCase

REPO = Path(__file__).resolve().parents[1]
IMAGE_SERVICE = REPO / "medmarshrut_image_service"
FORBIDDEN = ("result", "draft", "confidence", "model_version", "reason", "threshold", "Модель предполагает")


def load_synthetic():
    spec = importlib.util.spec_from_file_location("stand_synthetic_dicom", REPO / "demo_stand" / "synthetic_dicom.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNTHETIC = load_synthetic()
DEMO_TEXTS = json.loads((REPO / "demo_stand" / "conclusions.demo.json").read_text(encoding="utf-8"))
TASK = {"ct": "ct_general", "mr": "mr_general", "mg": "mg_screening_2d", "xr": "xr_general"}


def service_check(archive: bytes, manifest: dict) -> subprocess.CompletedProcess:
    """The image service's own parse_manifest + inspect_archive, in its folder and its own process."""
    with tempfile.TemporaryDirectory() as tmp:
        zip_path, manifest_path = Path(tmp) / "a.zip", Path(tmp) / "m.json"
        zip_path.write_bytes(archive)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        script = ("import json, sys\nfrom dicom_ingest import inspect_archive, parse_manifest\n"
                  "m = parse_manifest(open(sys.argv[2], encoding='utf-8').read())\n"
                  "r = inspect_archive(open(sys.argv[1], 'rb').read(), m)\nprint(r['instance_count'])\n")
        return subprocess.run([sys.executable, "-B", "-c", script, str(zip_path), str(manifest_path)],
                              cwd=IMAGE_SERVICE, capture_output=True, text=True, timeout=60)


def two_studies() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for prefix, variant in (("a", 1), ("b", 2)):
            archive, _ = SYNTHETIC.build_study("ct", variant)
            with zipfile.ZipFile(io.BytesIO(archive)) as source:
                for name in source.namelist():
                    target.writestr(f"{prefix}/{name}", source.read(name))
    return output.getvalue()


def zipped(entries: list[tuple[str, int]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, size in entries:
            archive.writestr(name, b"\0" * size)
    return output.getvalue()


class ManifestTests(unittest.TestCase):
    def test_manifest_from_kit_archives_passes_the_real_check(self):
        for kind in ("ct", "mr", "mg", "xr"):
            with self.subTest(kind=kind):
                archive, expected = SYNTHETIC.build_study(kind, 3)
                manifest = build_manifest(archive, TASK[kind])
                self.assertEqual(manifest, expected)
                result = service_check(archive, manifest)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(int(result.stdout), {"mg": 4, "xr": 1}.get(kind, 3))

    def test_two_studies_rejected(self):
        with self.assertRaises(GatewayError) as caught:
            build_manifest(two_studies(), "ct_general")
        self.assertIn("несколько исследований", caught.exception.message)

    def test_limits_rejected_before_any_file_is_read(self):
        cases = {"больше 512": zipped([(f"f{i}.dcm", 1) for i in range(513)]),
                 "40 МиБ": zipped([("big.dcm", 40 * 1024 * 1024 + 1)]),
                 "200 МиБ": zipped([(f"f{i}.dcm", 35 * 1024 * 1024) for i in range(6)])}
        for words, archive in cases.items():
            with self.subTest(limit=words), mock.patch("pydicom.dcmread") as reader:
                with self.assertRaises(GatewayError) as caught:
                    build_manifest(archive, "ct_general")
                self.assertIn(words, caught.exception.message)
                reader.assert_not_called()

    def test_not_a_zip_and_unknown_task(self):
        for archive, task in ((b"not a zip", "ct_general"), (SYNTHETIC.build_study("ct")[0], "xray")):
            with self.assertRaises(GatewayError):
                build_manifest(archive, task)


class PngTests(unittest.TestCase):
    def dataset(self, photometric: str) -> bytes:
        from pydicom import dcmread
        ds = dcmread(io.BytesIO(SYNTHETIC.instance("ct", "1.2.3", "1.2.3.4", "1.2.3.4.5", 0, 0)))
        ds.PhotometricInterpretation = photometric
        output = io.BytesIO()
        ds.save_as(output, enforce_file_format=True)
        return output.getvalue()

    def test_16_bit_slice_becomes_8_bit_png_of_the_same_size(self):
        image = Image.open(io.BytesIO(dicom_to_png(self.dataset("MONOCHROME2"))))
        self.assertEqual((image.format, image.mode, image.size), ("PNG", "L", (256, 256)))
        self.assertEqual(image.getextrema(), (0, 255))

    def test_monochrome1_is_inverted(self):
        normal = Image.open(io.BytesIO(dicom_to_png(self.dataset("MONOCHROME2"))))
        inverted = Image.open(io.BytesIO(dicom_to_png(self.dataset("MONOCHROME1"))))
        self.assertTrue(all(a + b == 255 for a, b in zip(normal.getdata(), inverted.getdata())))


class RegistryFake:
    """In-memory study_registry plus what the path screens need from the store."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.plains: dict[str, dict] = {}

    def plain_text(self, job_id):
        return self.plains.get(job_id)

    def save_plain_text(self, job_id, body, physician_id, lost_facts):
        self.plains[job_id] = {"text": body, "physician_id": physician_id, "lost_facts": lost_facts,
                               "approved_at": "2026-10-05T10:00:00+00:00"}
        return self.plains[job_id]

    def register_study(self, job_id, clinic_id, patient_ref, task, title, kit, role, by, consent_at):
        self.rows.setdefault(job_id, {"job_id": job_id, "clinic_id": clinic_id, "patient_ref": patient_ref, "task": task,
                                      "title": title, "kit": kit, "uploaded_by_role": role, "uploaded_by": by,
                                      "consent_at": consent_at.isoformat() if consent_at else None,
                                      "created_at": "2026-10-04T10:00:00+00:00"})
        return self.rows[job_id]

    def studies(self, clinic_id, patient_ref=None):
        return [r for r in self.rows.values() if r["clinic_id"] == clinic_id and (patient_ref is None or r["patient_ref"] == patient_ref)]

    def study(self, clinic_id, job_id):
        row = self.rows.get(job_id)
        return row if row and row["clinic_id"] == clinic_id else None

    def explanation(self, clinic_id, code):
        return {"seen": "Врач подтвердил участок уплотнения", "means": "Терапевт посмотрит вас на приёме"}

    def pending_patient_messages(self, *_):
        return []


SERIES, SOPS = "1.2.3.4", ["1.2.3.4.1", "1.2.3.4.2", "1.2.3.4.3"]


def job(job_id: str, status: str = "awaiting_physician", *, demo: bool = True, reason: str | None = None) -> dict:
    study = {"task": "ct_general", "modality": "CT", "study_uid": "1.2.3", "protocol_name": "CHEST_STANDARD",
             "anatomy": "CHEST", "instance_count": 3,
             "series": {SERIES: {"instance_count": 3, "rows": 256, "columns": 256, "ordered_sop_uids": SOPS}}}
    finding = {"code": "DEMO_CT_INFILTRATE", "description": "участок уплотнения лёгочной ткани", "confidence": 0.91,
               "localization": {"series_uid": SERIES, "sop_uid": SOPS[1], "slice_index": 2}}
    result = {"kind": "model_inference", "model_version": "demo-scripted-1" if demo else "lung-ct-1.4",
              "limitations": ["Только КТ грудной клетки"], "input_quality": {}, "refusal_reason": None,
              "findings": [] if status == "manual_review" else [finding]}
    return {"id": job_id, "created_at": "2026-10-04T10:00:00+00:00", "status": status, "reason": reason,
            "study": study, "result": result, "edits": [], "confirmation": None, "routing_status": None,
            "draft": [] if status == "manual_review" else
            [{"finding_id": 0, "text": f"Модель предполагает: участок (срез 2, серия {SERIES}, экземпляр {SOPS[1]}; оценка 0.91)."}]}


def public(full: dict) -> dict:
    return {key: full[key] for key in ("id", "created_at", "status", "reason", "routing_status")}


def confirmed(full: dict, conclusion: str = "Заключение врача по КТ") -> dict:
    payload = {"finding_code": "DEMO_CT_INFILTRATE", "confidence": 0.91, "source_model": full["result"]["model_version"]}
    return {**full, "status": "confirmed", "routing_status": "sent",
            "confirmation": {"physician_id": "doctor-demo", "conclusion": conclusion,
                             "confirmed_at": "2026-10-04T11:00:00+00:00", "routing_payload": payload}}


class StudyRouteTests(GatewayTestCase):
    def setUp(self):
        super().setUp()
        self.store = RegistryFake()
        self.gateway.store = self.store
        self.gateway.demo_texts = DEMO_TEXTS
        self.store.register_study("job-own", "clinic-central", "demo-patient-1", "ct_general", "КТ", None,
                                  "patient", "demo-patient-1", None)
        self.store.register_study("job-foreign", "clinic-central", "other-patient", "ct_general", "КТ", None,
                                  "staff", "coordinator-natalia", None)
        self.jobs = {"job-own": job("job-own"), "job-foreign": job("job-foreign")}
        self.image.routes.update({
            ("GET", "/v1/review/job-own"): lambda r: self.full("job-own"),
            ("GET", "/v1/review/job-foreign"): lambda r: self.full("job-foreign"),
            ("GET", "/v1/studies/job-own"): lambda r: self.short("job-own"),
            ("GET", "/v1/studies/job-foreign"): lambda r: self.short("job-foreign"),
            ("GET", "/v1/review/job-own/images/*"): (200, SYNTHETIC.instance("ct", "1.2.3", SERIES, SOPS[1], 1, 0)),
        })
        self.path.routes[("GET", "/v1/episodes")] = (200, {"episode_ids": []})
        self.clinic.routes[("GET", "/v1/patients?limit=500")] = (200, {"patients": [
            {"patient_ref": "demo-patient-1", "full_name": "Демо-пациент"},
            {"patient_ref": "other-patient", "full_name": "Другой пациент"}]})

    def full(self, job_id):
        return (200, self.jobs[job_id]) if job_id in self.jobs else (404, {"error": "Not found"})

    def short(self, job_id):
        return (200, public(self.jobs[job_id])) if job_id in self.jobs else (404, {"error": "Not found"})

    def image_requests(self, method="GET", fragment="/images/"):
        return [r for r in self.image.requests if r["method"] == method and fragment in r["path"]]

    def assert_no_leak(self, body):
        encoded = json.dumps(body, ensure_ascii=False)
        for word in FORBIDDEN:
            self.assertNotIn(word, encoded)

    # ---------- patient ----------

    def test_patient_sees_only_status_before_confirmation(self):
        self.login("patient")
        status, _, body = self.call("GET", "/api/patient/studies", role="patient")
        self.assertEqual(status, 200, body)
        self.assertEqual([(s["id"], s["status"]) for s in body["studies"]], [("job-own", "awaiting")])
        self.assertNotIn("conclusion", body["studies"][0])
        self.assert_no_leak(body)
        status, _, _ = self.call("GET", f"/api/patient/studies/job-own/images/{SOPS[1]}.png", role="patient")
        self.assertEqual(status, 404)
        self.assertEqual(self.image_requests(), [])

    def test_patient_manual_review_hides_reason(self):
        self.jobs["job-own"] = job("job-own", "manual_review", reason="No supported finding above threshold")
        self.login("patient")
        status, _, body = self.call("GET", "/api/patient/studies", role="patient")
        self.assertEqual((status, body["studies"][0]["status"]), (200, "manual"))
        self.assert_no_leak(body)

    def test_patient_never_sees_foreign_study(self):
        self.jobs["job-foreign"] = confirmed(self.jobs["job-foreign"])
        self.login("patient")
        _, _, body = self.call("GET", "/api/patient/studies", role="patient")
        self.assertNotIn("job-foreign", json.dumps(body))
        status, _, _ = self.call("GET", f"/api/patient/studies/job-foreign/images/{SOPS[1]}.png", role="patient")
        self.assertEqual(status, 404)
        self.assertEqual(self.image_requests(), [])

    def test_patient_after_confirmation_gets_text_explanation_step_and_png(self):
        self.jobs["job-own"] = confirmed(self.jobs["job-own"])
        self.path.routes.update({("GET", "/v1/episodes"): (200, {"episode_ids": ["ep-1"]}),
                                 ("GET", "/v1/episodes/ep-1"): (200, {
                                     "id": "ep-1", "status": "active", "manual_reason": None, "created_at": "2026-10-04T11:00:00Z",
                                     "updated_at": "2026-10-04T11:00:00Z",
                                     "source_report": {"source_report_id": "job-own", "patient_ref": "demo-patient-1",
                                                       "confidence": 0.91, "source_model": "demo-scripted-1",
                                                       "conclusion": "Заключение врача по КТ", "finding_code": "DEMO_CT_INFILTRATE"},
                                     "plan_steps": [{"id": "s1", "kind": "appointment", "status": "open", "position": 1,
                                                     "description": "Приём терапевта в течение 24 часов"}],
                                     "audit_events": [{"details": {"confidence": 0.91}}]})})
        self.login("patient")
        status, _, body = self.call("GET", "/api/patient/studies", role="patient")
        self.assertEqual(status, 200, body)
        item = body["studies"][0]
        self.assertEqual((item["status"], item["conclusion"]), ("confirmed", "Заключение врача по КТ"))
        self.assertEqual(item["explanation"]["seen"], "Врач подтвердил участок уплотнения")
        self.assertEqual(item["episode"]["steps"][0]["description"], "Приём терапевта в течение 24 часов")
        self.assertEqual(item["image"], {"sop_uid": SOPS[1], "label": "Признак на срезе 2 из 3"})
        self.assertEqual(item["title"], "КТ органов грудной клетки")
        self.assert_no_leak(body)
        status, headers, png = self.call("GET", f"/api/patient/studies/job-own/images/{SOPS[1]}.png", role="patient")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertEqual(Image.open(io.BytesIO(png)).size, (256, 256))

    def test_restarted_image_service_shows_unavailable(self):
        del self.jobs["job-own"]
        self.login("patient")
        _, _, body = self.call("GET", "/api/patient/studies", role="patient")
        self.assertEqual((body["studies"][0]["status"], body["studies"][0]["message"]),
                         ("unavailable", "Недоступно: сервис снимков перезапущен"))
        self.login("doctor")
        status, _, body = self.call("GET", "/api/doctor/studies", role="doctor")
        self.assertEqual(status, 200, body)
        self.assertEqual({s["id"]: s["status"] for s in body["studies"]}, {"job-own": "unavailable", "job-foreign": "awaiting_physician"})

    # ---------- staff ----------

    def test_staff_manual_group_without_reason_or_model_output(self):
        self.jobs["job-foreign"] = job("job-foreign", "manual_review", reason="No supported finding above threshold")
        self.login("staff")
        status, _, body = self.call("GET", "/api/staff/studies/manual", role="staff")
        self.assertEqual(status, 200, body)
        self.assertEqual([(s["id"], s["patient"]) for s in body["manual"]], [("job-foreign", "Другой пациент")])
        self.assert_no_leak(body)
        self.assertEqual(self.image_requests(fragment="/v1/review/"), [])

    def test_staff_sees_confirmations_that_did_not_reach_the_path_service(self):
        self.jobs["job-own"] = {**confirmed(self.jobs["job-own"]), "routing_status": "failed"}
        self.login("staff")
        _, _, body = self.call("GET", "/api/staff/studies/manual", role="staff")
        self.assertEqual(body["not_routed"][0]["warning"], "Заключение подтверждено, но не дошло до сервиса маршрута")

    def test_images_and_model_output_only_for_doctor(self):
        for role in ("patient", "staff"):
            self.login(role)
            for route in ("/api/doctor/studies", "/api/doctor/studies/job-own", f"/api/doctor/studies/job-own/images/{SOPS[1]}.png"):
                self.assertEqual(self.call("GET", route, role=role)[0], 403, (role, route))
        self.login("doctor")
        status, headers, png = self.call("GET", f"/api/doctor/studies/job-own/images/{SOPS[1]}.png", role="doctor")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertEqual(Image.open(io.BytesIO(png)).mode, "L")

    # ---------- doctor ----------

    def test_doctor_detail_demo_hides_score_and_uses_stand_text(self):
        self.login("doctor")
        status, _, body = self.call("GET", "/api/doctor/studies/job-own", role="doctor")
        self.assertEqual(status, 200, body)
        study = body["study"]
        self.assertTrue(study["demo"])
        self.assertNotIn("confidence", study["findings"][0])
        self.assertEqual(study["findings"][0]["place"], "Признак на срезе 2 из 3")
        self.assertEqual(study["templates"], {"DEMO_CT_INFILTRATE": DEMO_TEXTS["DEMO_CT_INFILTRATE"]})
        self.assertEqual([i["label"] for i in study["images"]], ["Срез 1 из 3", "Срез 2 из 3", "Срез 3 из 3"])
        self.assertNotIn("draft", body)

    def test_preview_shows_step_by_approved_rule(self):
        sent = []

        def dry_run(request):
            sent.append(json.loads(request["body"]))
            return 200, {"dry_run": True, "steps": [{"title": "Приём терапевта в течение 24 часов"}],
                         "manual_reason": None, "rule_version": "demo-rules-7"}
        self.path.routes[("POST", "/v1/rules/dry-run")] = dry_run
        self.login("doctor")
        _, _, body = self.call("GET", "/api/doctor/studies/job-own", role="doctor")
        preview = body["study"]["preview"]["DEMO_CT_INFILTRATE"]
        self.assertEqual([s["title"] for s in preview["steps"]], ["Приём терапевта в течение 24 часов"])
        self.assertIsNone(preview["manual_reason"])
        self.assertEqual(preview["rule_version"], "demo-rules-7")
        self.assertEqual(preview["explanation"]["means"], "Терапевт посмотрит вас на приёме")
        # confidence не уходит в сервис пути и не возвращается в предпросмотре
        self.assertEqual(sent[-1], {"study_type": "ct", "anatomy": "CHEST",
                                    "protocol_name": "CHEST_STANDARD", "finding_code": "DEMO_CT_INFILTRATE"})
        self.assertNotIn("confidence", preview)

    def test_preview_shows_manual_reason_for_unapproved_rule(self):
        self.path.routes[("POST", "/v1/rules/dry-run")] = (200, {"dry_run": True, "steps": [],
            "manual_reason": "rule_not_approved", "rule_version": "demo-rules-7"})
        self.login("doctor")
        _, _, body = self.call("GET", "/api/doctor/studies/job-own", role="doctor")
        preview = body["study"]["preview"]["DEMO_CT_INFILTRATE"]
        self.assertEqual(preview["steps"], [])
        self.assertEqual(preview["manual_reason"], "rule_not_approved")
        self.assertEqual(preview["manual_reason_text"], "Правило ещё не утверждено клиникой: нужен план врача")

    def test_preview_is_null_when_path_service_is_down(self):
        self.path.mode = "drop"
        self.login("doctor")
        status, _, body = self.call("GET", "/api/doctor/studies/job-own", role="doctor")
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["study"]["preview"])

    def test_preview_is_doctor_only(self):
        self.path.routes[("POST", "/v1/rules/dry-run")] = (200, {"dry_run": True, "steps": [],
            "manual_reason": None, "rule_version": "demo-rules-7"})
        for role in ("patient", "staff"):
            self.login(role)
            status, _, _ = self.call("GET", "/api/doctor/studies/job-own", role=role)
            self.assertEqual(status, 403, role)

    def test_template_of_a_real_model_has_no_scores_or_uids(self):
        self.jobs["job-own"] = job("job-own", demo=False)
        self.login("doctor")
        _, _, body = self.call("GET", "/api/doctor/studies/job-own", role="doctor")
        template = body["study"]["templates"]["DEMO_CT_INFILTRATE"]
        self.assertTrue(template.startswith("КТ органов грудной клетки."))
        for word in ("0.91", "оценка", SERIES, SOPS[1], "Модель"):
            self.assertNotIn(word, template)
        self.assertEqual(body["study"]["findings"][0]["confidence"], 0.91)

    def test_manual_review_reason_is_translated_for_the_doctor(self):
        self.jobs["job-own"] = job("job-own", "manual_review", reason="Incomplete series: expected SOP Instance UIDs do not match")
        self.jobs["job-foreign"] = job("job-foreign", "manual_review", reason="Something new")
        self.login("doctor")
        _, _, body = self.call("GET", "/api/doctor/studies", role="doctor")
        reasons = {s["id"]: s["reason"] for s in body["studies"]}
        self.assertEqual(reasons["job-own"]["text"], "Серия неполная: в архиве не все срезы из перечня исследования.")
        self.assertEqual(reasons["job-foreign"]["original"], "Something new")
        self.assertIn("без перевода", reasons["job-foreign"]["text"])

    def test_confirm_takes_physician_from_session_and_patient_from_registry(self):
        sent = []

        def confirm(request):
            sent.append(json.loads(request["body"]))
            return 200, {**confirmed(self.jobs["job-own"], sent[-1]["conclusion"]), "routing_status": "failed"}
        self.image.routes[("POST", "/v1/review/job-own")] = confirm
        self.login("doctor")
        for text, edits in ((DEMO_TEXTS["DEMO_CT_INFILTRATE"], []), ("Заключение изменено врачом", [EDITED])):
            status, _, body = self.call("POST", "/api/doctor/studies/job-own/confirm", role="doctor", body={
                "conclusion": text, "physician_id": "attacker", "patient_ref": "attacker", "edits": ["подделка"]})
            self.assertEqual(status, 200, body)
            self.assertEqual(sent[-1], {"physician_id": "doctor-demo", "conclusion": text, "edits": edits,
                                        "finding_code": "DEMO_CT_INFILTRATE", "patient_ref": "demo-patient-1"})
            self.assertEqual(body["next"], {"warning": "Заключение подтверждено, но не дошло до сервиса маршрута"})

    def test_confirm_body_over_8192_bytes_is_not_sent(self):
        self.login("doctor")
        for text in ("€" * 3500, "а" * 3501):
            status, _, body = self.call("POST", "/api/doctor/studies/job-own/confirm", role="doctor", body={"conclusion": text})
            self.assertEqual(status, 400, body)
        self.assertEqual(self.image_requests("POST", "/v1/review/"), [])

    def test_confirm_returns_episode_and_first_step(self):
        self.image.routes[("POST", "/v1/review/job-own")] = lambda r: (200, confirmed(self.jobs["job-own"]))
        self.path.routes.update({("GET", "/v1/episodes"): (200, {"episode_ids": ["ep-1"]}),
                                 ("GET", "/v1/episodes/ep-1"): (200, {
                                     "id": "ep-1", "status": "manual_review", "manual_reason": "rule_not_approved",
                                     "source_report": {"source_report_id": "job-own"}, "plan_steps": []})})
        self.login("doctor")
        status, _, body = self.call("POST", "/api/doctor/studies/job-own/confirm", role="doctor",
                                    body={"conclusion": "Заключение врача"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["next"]["status"], "manual_review")
        self.assertEqual(body["next"]["reason"], "Правило ещё не утверждено клиникой: нужен план врача")
        self.assertIsNone(body["next"]["step_status"])

    def test_confirm_next_carries_step_status_for_the_route_chain(self):
        self.image.routes[("POST", "/v1/review/job-own")] = lambda r: (200, confirmed(self.jobs["job-own"]))
        self.path.routes.update({("GET", "/v1/episodes"): (200, {"episode_ids": ["ep-1"]}),
                                 ("GET", "/v1/episodes/ep-1"): (200, {
                                     "id": "ep-1", "status": "active", "source_report": {"source_report_id": "job-own"},
                                     "plan_steps": [{"id": "s-1", "kind": "appointment", "status": "confirmed",
                                                     "description": "Приём терапевта в течение 24 часов"}]})})
        self.login("doctor")
        status, _, body = self.call("POST", "/api/doctor/studies/job-own/confirm", role="doctor",
                                    body={"conclusion": "Заключение врача"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["next"]["step"], "Приём терапевта в течение 24 часов")
        self.assertEqual(body["next"]["step_status"], "confirmed")

    # ---------- upload ----------

    def upload(self, archive, *, role="patient", query="?task=ct_general&consent=1", headers=None, route=None):
        self.login(role)
        sent = {"Content-Type": "application/zip", **(headers or {})}
        return self.call("POST", (route or f"/api/{role}/studies") + query, role=role, raw=archive, headers=sent)

    def test_service_codes_become_study_status(self):
        archive, _ = SYNTHETIC.build_study("ct", 5)
        for code, status, expected in ((201, "awaiting_physician", "awaiting"), (202, "manual_review", "manual"),
                                       (422, "manual_review", "manual"), (503, "manual_review", "manual"),
                                       (504, "manual_review", "manual")):
            with self.subTest(code=code):
                job_id = f"new-{code}"
                self.image.routes[("POST", "/v1/studies")] = (code, {"id": job_id, "created_at": "2026-10-04T10:00:00Z",
                                                                     "status": status, "reason": "Inference failed: x",
                                                                     "routing_status": None})
                http_status, _, body = self.upload(archive)
                self.assertEqual(http_status, 201, body)
                self.assertEqual(body["study"]["status"], expected)
                self.assert_no_leak(body)
                row = self.store.rows[job_id]
                self.assertEqual((row["patient_ref"], row["uploaded_by_role"], row["task"]), ("demo-patient-1", "patient", "ct_general"))
                self.assertIsNotNone(row["consent_at"])
        request = self.image_requests("POST", "/v1/studies")[-1]
        manifest = json.loads(request["headers"]["X-Study-Manifest"])
        self.assertEqual((manifest["task"], len(next(iter(manifest["series"].values())))), ("ct_general", 3))

    def test_gateway_rejects_type_size_consent_and_two_studies(self):
        archive, _ = SYNTHETIC.build_study("ct", 6)
        cases = [(self.upload(archive, headers={"Content-Type": "application/octet-stream"}), 415),
                 (self.upload(b"x" * 10, headers={"Content-Length": str(50 * 1024 * 1024 + 1)}), 413),
                 (self.upload(archive, query="?task=ct_general"), 400),
                 (self.upload(archive, query="?task=xray&consent=1"), 400),
                 (self.upload(two_studies()), 400)]
        for (status, _, body), expected in cases:
            self.assertEqual(status, expected, body)
        self.assertEqual(self.image_requests("POST", "/v1/studies"), [])

    def test_staff_upload_names_the_patient_and_patient_cannot_use_it(self):
        archive, _ = SYNTHETIC.build_study("ct", 7)
        self.image.routes[("POST", "/v1/studies")] = (201, {"id": "job-staff", "created_at": "2026-10-04T10:00:00Z",
                                                            "status": "awaiting_physician", "reason": None, "routing_status": None})
        status, _, body = self.upload(archive, role="staff", query="?task=ct_general&patient_ref=demo-patient-1")
        self.assertEqual(status, 201, body)
        self.assertEqual(self.store.rows["job-staff"]["uploaded_by"], "coordinator-natalia")
        self.assertEqual(self.upload(archive, role="patient", route="/api/staff/studies", query="?task=ct_general")[0], 403)

    def test_demo_kit_list_and_submit(self):
        kit = Path(self.tmp.name) / "kit"
        kit.mkdir()
        archive, _ = SYNTHETIC.build_study("ct", 8)
        (kit / "upload-ct-clear.zip").write_bytes(archive)
        (kit / "kit.json").write_text(json.dumps({
            "upload-ct-clear": {"kind": "ct", "title": "КТ органов грудной клетки", "task": "ct_general", "archive": "upload-ct-clear.zip"},
            "demo-patient-6": {"kind": "ct", "title": "КТ органов грудной клетки", "task": "ct_general", "archive": "upload-ct-clear.zip"}},
            ensure_ascii=False), encoding="utf-8")
        self.image.routes[("POST", "/v1/studies")] = (422, {"id": "job-kit", "created_at": "2026-10-04T10:00:00Z",
                                                            "status": "manual_review", "reason": "No supported finding above threshold",
                                                            "routing_status": None})
        self.login("patient")
        _, _, body = self.call("GET", "/api/demo/studies", role="patient")
        self.assertEqual([s["name"] for s in body["studies"]], ["upload-ct-clear"])
        self.assertEqual(self.call("POST", "/api/demo/studies/demo-patient-6/submit", role="patient", body={"consent": True})[0], 404)
        status, _, body = self.call("POST", "/api/demo/studies/upload-ct-clear/submit", role="patient", body={"consent": True})
        self.assertEqual((status, body["study"]["status"]), (201, "manual"))
        self.assert_no_leak(body)
        self.assertEqual(self.store.rows["job-kit"]["kit"], "upload-ct-clear")


if __name__ == "__main__":
    unittest.main()
