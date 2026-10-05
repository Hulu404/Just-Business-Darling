import io
import hmac
import hashlib
import json
import unittest
import zipfile
import tempfile
import time
from unittest.mock import MagicMock, patch
from pathlib import Path

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (CTImageStorage, MRImageStorage,
                         DigitalMammographyXRayImageStorageForPresentation,
                         ExplicitVRLittleEndian, generate_uid)

from model import TestBackend, LocalONNXBackend
from service import StudyService, ReviewError


def synthetic_dicom(modality, study_uid, series_uid, sop_uid, number=1, view=None, side=None):
    sop_class = {"CT": CTImageStorage, "MR": MRImageStorage,
                 "MG": DigitalMammographyXRayImageStorageForPresentation}[modality]
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    ds = FileDataset("synthetic.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = modality
    ds.ImageType = ["ORIGINAL", "PRIMARY"]
    ds.Rows = ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelSpacing = ["0.5", "0.5"]
    ds.ProtocolName = "SYNTHETIC-PROTOCOL"
    ds.BodyPartExamined = "CHEST"
    ds.PixelData = bytes(8)
    if modality in {"CT", "MR"}:
        if modality == "CT":
            ds.RescaleSlope = "1"
            ds.RescaleIntercept = "-1024"
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0, 0, number]
        ds.InstanceNumber = number
    else:
        ds.ViewPosition = view
        ds.ImageLaterality = side
        ds.PresentationIntentType = "FOR PRESENTATION"
    output = io.BytesIO()
    ds.save_as(output, enforce_file_format=True)
    return output.getvalue()


def bundle(modality="CT", numbers=(1, 2, 3), missing=None, bad_name=None, bad_view=None):
    study_uid, series_uid = generate_uid(), generate_uid()
    expected = [generate_uid() for _ in numbers]
    manifest = {"task": {"CT": "ct_general", "MR": "mr_general",
                          "MG": "mg_screening_2d"}[modality],
                "study_uid": study_uid, "series": {series_uid: expected}}
    output = io.BytesIO()
    views = [("L", "CC"), ("L", "MLO"), ("R", "CC"), ("R", "MLO")]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for i, (number, uid) in enumerate(zip(numbers, expected)):
            if i == missing:
                continue
            side, view = views[i] if modality == "MG" else (None, None)
            if i == 0 and bad_view is not None:
                view = bad_view
            archive.writestr(bad_name if i == 0 and bad_name else f"image{i}.dcm",
                             synthetic_dicom(modality, study_uid, series_uid, uid, number, view, side))
    return output.getvalue(), json.dumps(manifest)


class IngestTests(unittest.TestCase):
    def test_ct_and_mr_validate_but_require_model(self):
        for modality in ("CT", "MR"):
            result = StudyService().submit(*bundle(modality))
            self.assertEqual(result["status"], "manual_review")
            self.assertEqual(result["reason"], "No local model backend is configured")
            self.assertEqual(result["study"]["instance_count"], 3)

    def test_explicit_test_backend_has_no_diagnosis(self):
        result = StudyService(TestBackend()).submit(*bundle())
        self.assertEqual(result["status"], "test_only")
        self.assertEqual(result["result"]["kind"], "test_only")
        self.assertNotIn("finding_code", result["result"])
        with self.assertRaises(ReviewError):
            StudyService(TestBackend()).confirm(result["id"], {})

    def test_incomplete_and_irregular_series(self):
        incomplete = StudyService().submit(*bundle(missing=1))
        self.assertEqual(incomplete["status"], "manual_review")
        self.assertIn("Incomplete series", incomplete["reason"])
        irregular = StudyService().submit(*bundle(numbers=(1, 2, 4)))
        self.assertIn("Irregular slice spacing", irregular["reason"])

    def test_mammography_four_views_and_missing_view(self):
        self.assertEqual(StudyService(TestBackend()).submit(*bundle("MG", (1, 2, 3, 4)))["status"], "test_only")
        result = StudyService().submit(*bundle("MG", (1, 2, 3, 4), missing=3))
        self.assertEqual(result["status"], "manual_review")
        self.assertIn("Incomplete series", result["reason"])
        unsupported = StudyService().submit(*bundle("MG", (1, 2, 3, 4), bad_view="LM"))
        self.assertIn("Unsupported or missing mammography view", unsupported["reason"])

    def test_zip_traversal_is_rejected(self):
        result = StudyService().submit(*bundle(bad_name="../escape.dcm"))
        self.assertEqual(result["status"], "manual_review")
        self.assertIn("Unsafe archive", result["reason"])

    def test_oversized_archive_and_bad_manifest(self):
        archive, manifest = bundle()
        oversized = StudyService().submit(b"0" * (50 * 1024 * 1024 + 1), manifest)
        self.assertIn("exceeds 50 MiB", oversized["reason"])
        malformed = StudyService().submit(archive, '{"task": [], "study_uid": "1.2", "series": {}}')
        self.assertEqual(malformed["reason"], "Unsupported task or protocol")

    def test_review_flow_and_no_public_model_result(self):
        class SyntheticModel(TestBackend):
            def infer_local(self, study, task, archive):
                series_uid, series = next(iter(study["series"].items()))
                return {"kind": "model_inference", "backend": "SyntheticModelForTest",
                        "model_version": "fixture-1", "weights_sha256": "fixture-only",
                        "preprocessing_version": "fixture-1", "modality": study["modality"],
                        "anatomy": study["anatomy"], "diagnostic_task": "synthetic check",
                        "input_quality": {"pixel_decode_ok": True}, "limitations": ["synthetic"],
                        "findings": [{"code": "TEST", "description": "тестовый признак",
                                      "confidence": 0.7, "localization": {"series_uid": series_uid,
                                      "sop_uid": series["ordered_sop_uids"][0], "slice_index": 1}}],
                        "refusal_reason": None}
        service = StudyService(SyntheticModel())
        job = service.submit(*bundle())
        self.assertEqual(job["status"], "awaiting_physician")
        self.assertEqual(job["draft"][0]["finding_id"], 0)
        self.assertNotIn("draft", service.public(job["id"]))
        self.assertNotIn("result", service.public(job["id"]))
        sop = job["result"]["findings"][0]["localization"]["sop_uid"]
        self.assertIsNotNone(service.image(job["id"], sop))
        confirmed = service.confirm(job["id"], {"physician_id": "doctor-1",
            "conclusion": "Подтверждено врачом на тестовых данных", "edits": ["исправлена формулировка"],
            "finding_code": "TEST"})
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["confirmation"]["routing_payload"]["conclusion"],
                         "Подтверждено врачом на тестовых данных")
        with self.assertRaises(ReviewError):
            service.confirm(job["id"], {"physician_id": "doctor-1", "conclusion": "x",
                                             "edits": [], "finding_code": "TEST"})

    def test_local_weights_checksum_failure_is_manual_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "model.onnx").write_bytes(b"invalid fixture")
            config = {"model_version": "1", "preprocessing_version": "monochrome-v1",
                      "modality": "CT", "anatomy": "CHEST", "diagnostic_task": "specific task",
                      "protocol_name": "SYNTHETIC-PROTOCOL", "task": "ct_general",
                      "weights_file": "model.onnx", "weights_sha256": "0" * 64,
                      "input_size": [16, 16], "labels": [{"code": "X", "description": "x", "threshold": 0.7}],
                      "limitations": []}
            (path / "model.json").write_text(json.dumps(config), encoding="utf-8")
            job = StudyService(LocalONNXBackend(path / "model.json")).submit(*bundle())
            self.assertEqual(job["status"], "manual_review")
            self.assertIn("SHA-256 mismatch", job["reason"])

    def test_incompatible_timeout_and_memory_fail_closed(self):
        class FailingBackend(TestBackend):
            def __init__(self, failure):
                super().__init__()
                self.failure = failure

            def check_compatibility(self, study, task):
                if self.failure == "protocol":
                    return False, "No model validated for this protocol"
                return True, ""

            def infer_local(self, study, task, archive):
                if self.failure == "memory":
                    raise MemoryError()
                time.sleep(0.03)
                return {}

        for failure, expected in (("protocol", "No model validated"),
                                  ("memory", "Insufficient memory"),
                                  ("timeout", "timed out")):
            service = StudyService(FailingBackend(failure), timeout_seconds=0.001)
            job = service.submit(*bundle())
            self.assertEqual(job["status"], "manual_review")
            self.assertIn(expected, job["reason"])
            self.assertIsNone(job["confirmation"])

    def test_test_backend_never_routes(self):
        with patch("service.urlopen") as send:
            service = StudyService(TestBackend(), router_url="http://127.0.0.1:8765/v1/reports", router_secret="test-secret")
            job = service.submit(*bundle())
            self.assertEqual(job["status"], "test_only")
            with self.assertRaises(ReviewError):
                service.confirm(job["id"], {"physician_id": "doctor-1", "conclusion": "x",
                                            "edits": [], "finding_code": "TEST"})
            send.assert_not_called()

    def test_confirmed_mr_report_is_signed_and_sent(self):
        class SyntheticModel(TestBackend):
            def infer_local(self, study, task, archive):
                series_uid, series = next(iter(study["series"].items()))
                return {"kind": "model_inference", "backend": "SyntheticModelForTest",
                        "model_version": "fixture-1", "weights_sha256": "fixture-only",
                        "preprocessing_version": "fixture-1", "modality": "MR", "anatomy": "CHEST",
                        "diagnostic_task": "synthetic check", "input_quality": {"pixel_decode_ok": True},
                        "limitations": ["synthetic"], "findings": [{"code": "TEST", "description": "synthetic",
                        "confidence": 0.01, "localization": {"series_uid": series_uid,
                        "sop_uid": series["ordered_sop_uids"][0], "slice_index": 1}}],
                        "refusal_reason": None}

        secret = "test-shared-secret-long"
        service = StudyService(SyntheticModel(), router_url="http://127.0.0.1:8765/v1/reports", router_secret=secret)
        job = service.submit(*bundle("MR"))
        response = MagicMock()
        response.status = 201
        response.__enter__.return_value = response
        with patch("service.urlopen", return_value=response) as send:
            result = service.confirm(job["id"], {"physician_id": "doctor-1", "conclusion": "reviewed",
                "edits": [], "finding_code": "TEST", "patient_ref": "patient-1"})
        self.assertEqual(result["routing_status"], "sent")
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["study_type"], "mr")
        self.assertEqual(payload["confirmation_status"], "confirmed")
        self.assertEqual(payload["physician_id"], "doctor-1")
        self.assertEqual(payload["source_report_version"], 1)
        self.assertEqual(payload["patient_ref"], "patient-1")
        timestamp = request.get_header("X-path-timestamp")
        expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + request.data, hashlib.sha256).hexdigest()
        self.assertEqual(request.get_header("X-path-signature"), expected)



def xray_dicom(modality, study_uid, series_uid, sop_uid, view, *, sop_class=None, transfer=None, imager_spacing=False):
    from pydicom.uid import ComputedRadiographyImageStorage, DigitalXRayImageStorageForPresentation
    sop_class = sop_class or {"CR": ComputedRadiographyImageStorage, "DX": DigitalXRayImageStorageForPresentation}[modality]
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = transfer or ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    ds = FileDataset("synthetic.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = modality
    ds.ImageType = ["ORIGINAL", "PRIMARY"]
    ds.Rows = ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME1"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    if imager_spacing:
        ds.ImagerPixelSpacing = ["0.15", "0.15"]
    else:
        ds.PixelSpacing = ["0.15", "0.15"]
    ds.ProtocolName = "CHEST_PA"
    ds.BodyPartExamined = "CHEST"
    ds.ViewPosition = view
    if modality == "DX":
        ds.PresentationIntentType = "FOR PRESENTATION"
    if transfer:  # a compressed syntax needs encapsulated pixel data to be written at all
        from pydicom.encaps import encapsulate
        ds.PixelData = encapsulate([bytes(8)])
    else:
        ds.PixelData = bytes(8)
    output = io.BytesIO()
    ds.save_as(output, enforce_file_format=True)
    return output.getvalue()


def xray_bundle(modality="DX", views=("PA",), **options):
    study_uid, series_uid = generate_uid(), generate_uid()
    expected = [generate_uid() for _ in views]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for i, (view, uid) in enumerate(zip(views, expected)):
            archive.writestr(f"image{i}.dcm", xray_dicom(modality, study_uid, series_uid, uid, view, **options))
    return output.getvalue(), json.dumps({"task": "xr_general", "study_uid": study_uid, "series": {series_uid: expected}})


class XRayTests(unittest.TestCase):
    def test_cr_and_dx_chest_xray_validate(self):
        for modality, options in (("DX", {}), ("CR", {"imager_spacing": True})):
            with self.subTest(modality=modality):
                result = StudyService().submit(*xray_bundle(modality, ("PA", "LL"), **options))
                self.assertEqual(result["reason"], "No local model backend is configured")
                self.assertEqual((result["study"]["modality"], result["study"]["task"]), (modality, "xr_general"))
                self.assertEqual(StudyService(TestBackend()).submit(*xray_bundle(modality, **options))["status"], "test_only")

    def test_extra_or_missing_frontal_view_is_rejected(self):
        for views in (("PA", "AP"), ("LL",), ("PA", "LL", "RL")):
            with self.subTest(views=views):
                result = StudyService().submit(*xray_bundle("DX", views))
                self.assertEqual(result["status"], "manual_review")
                self.assertIn("Chest X-ray requires one PA or AP view", result["reason"])

    def test_unsupported_sop_class_and_compressed_syntax(self):
        from pydicom.uid import JPEGLosslessSV1
        wrong = StudyService().submit(*xray_bundle("DX", sop_class=CTImageStorage))
        self.assertIn("Unsupported DICOM SOP class", wrong["reason"])
        compressed = StudyService().submit(*xray_bundle("DX", transfer=JPEGLosslessSV1))
        self.assertIn("Unsupported transfer syntax", compressed["reason"])

    def test_confirmed_xray_is_sent_as_xray_with_projection(self):
        class SyntheticModel(TestBackend):
            def infer_local(self, study, task, archive):
                series_uid, series = next(iter(study["series"].items()))
                sop = next(uid for uid, view in series["projections"].items() if view == "PA")
                return {"kind": "model_inference", "backend": "SyntheticModelForTest", "model_version": "fixture-1",
                        "weights_sha256": "fixture-only", "preprocessing_version": "fixture-1", "modality": study["modality"],
                        "anatomy": "CHEST", "diagnostic_task": "synthetic check", "input_quality": {"pixel_decode_ok": True},
                        "limitations": ["synthetic"], "findings": [{"code": "TEST", "description": "synthetic", "confidence": 0.5,
                        "localization": {"series_uid": series_uid, "sop_uid": sop, "projection": "PA"}}], "refusal_reason": None}

        service = StudyService(SyntheticModel(), router_url="http://127.0.0.1:8765/v1/reports", router_secret="test-shared-secret-long")
        job = service.submit(*xray_bundle("CR", ("PA", "LL"), imager_spacing=True))
        self.assertEqual(job["status"], "awaiting_physician")
        self.assertIn("PA", job["draft"][0]["text"])
        sop = job["result"]["findings"][0]["localization"]["sop_uid"]
        self.assertIsNotNone(service.image(job["id"], sop))
        response = MagicMock()
        response.status = 201
        response.__enter__.return_value = response
        with patch("service.urlopen", return_value=response) as send:
            result = service.confirm(job["id"], {"physician_id": "doctor-1", "conclusion": "reviewed", "edits": [],
                                                 "finding_code": "TEST", "patient_ref": "patient-1"})
        self.assertEqual(result["routing_status"], "sent")
        self.assertEqual(json.loads(send.call_args.args[0].data)["study_type"], "xray")

if __name__ == "__main__":
    unittest.main()
