import io
import json
import unittest
import zipfile

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (CTImageStorage, MRImageStorage,
                         DigitalMammographyXRayImageStorageForPresentation,
                         ExplicitVRLittleEndian, generate_uid)

from model import TestBackend
from service import StudyService


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
        class UnapprovedBackend(TestBackend):
            pass
        with self.assertRaisesRegex(ValueError, "Only the explicitly marked TestBackend"):
            StudyService(UnapprovedBackend())

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


if __name__ == "__main__":
    unittest.main()
