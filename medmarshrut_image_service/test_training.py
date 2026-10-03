import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dataset_manifest import read_manifest, split_patients, validate_split
from evaluation import binary_metrics, evaluation_report
from model import LocalONNXBackend, ModelError
from preprocessing import PREPROCESSING_VERSION
from training import approve, task_config, train, write_json


class TrainingContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {"model_version": "fixture-1", "task": "ct_general", "modality": "CT",
            "anatomy": "CHEST", "protocol_name": "P1", "diagnostic_task": "synthetic target",
            "label_code": "SYN", "label_description": "synthetic finding", "input_size": [16, 16],
            "threshold": 0.5, "epochs": 1, "batch_size": 2, "learning_rate": 0.001, "seed": 7,
            "preprocessing_version": PREPROCESSING_VERSION, "limitations": ["synthetic only"]}
        write_json(self.root / "task.json", self.config)

    def _manifest(self):
        rows = []
        for i, site in enumerate(["siteA", "siteA", "siteA", "siteA", "siteB", "siteB"]):
            image = f"image{i}.dcm"
            (self.root / image).write_bytes(b"fixture")
            rows.append({"study_id": f"1.2.3.{i}", "patient_id": f"patient{i}", "institution_id": site,
                "modality": "CT", "anatomy": "CHEST", "protocol_name": "P1", "study_type": "routine",
                "image_path": image, "image_sha256": hashlib.sha256(b"fixture").hexdigest(),
                "label": i % 2, "label_source": {"kind": "expert", "reference": f"ref{i}"},
                "finding_location": {"series_uid": f"1.2.4.{i}", "sop_uid": f"1.2.5.{i}",
                    "region": "slice:1" if i % 2 else "none"}, "annotation_version": "v1"})
        path = self.root / "manifest.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return path, rows

    def test_manifest_split_external_and_revision(self):
        path, _ = self._manifest()
        rows, digest = read_manifest(path, task_config(self.root / "task.json"))
        parts = split_patients(rows, 7, "siteB")
        split = {"manifest_sha256": digest, "external_institution": "siteB", "patients": parts}
        validate_split(rows, split, digest)
        self.assertEqual(set(parts["external"]), {"patient4", "patient5"})
        self.assertEqual(len(set().union(*[set(v) for v in parts.values()])), 6)
        parts["validation"] = parts["train"][:]
        with self.assertRaises(ValueError):
            validate_split(rows, split, digest)

    def test_manifest_rejects_missing_localization_and_path_escape(self):
        path, rows = self._manifest()
        rows[1]["finding_location"]["region"] = "none"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "localization"):
            read_manifest(path, self.config)
        rows[1]["finding_location"]["region"] = "slice:1"
        rows[1]["image_path"] = "../outside.dcm"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "below manifest"):
            read_manifest(path, self.config)

    def test_metrics_and_undefined_denominators(self):
        m = binary_metrics([1, 1, 0, 0], [0.9, 0.2, 0.8, 0.1], 0.5)
        self.assertEqual((m["tp"], m["tn"], m["fp"], m["fn"]), (1, 1, 1, 1))
        self.assertAlmostEqual(m["sensitivity"], 0.5)
        self.assertAlmostEqual(m["specificity"], 0.5)
        self.assertIsNone(binary_metrics([1], [0.6], 0.5)["specificity"])
        report = evaluation_report([{"label": 1, "institution_id": "A", "study_type": "routine", "annotation_version": "v1"}], [0.2], 0.5)
        self.assertEqual(report["errors_by_study_type"]["routine"]["false_negative"], 1)

    def test_training_requires_explicit_data_authorization(self):
        with self.assertRaisesRegex(ValueError, "allow-real-data"):
            train(self.root / "missing", self.root / "task.json", self.root / "missing-split", self.root / "fixture-1", allow_real_data=False)

    def test_backend_requires_manual_approval(self):
        artifact = self.root / "fixture-1"
        artifact.mkdir()
        weights = b"not-a-real-onnx-model"
        (artifact / "model.onnx").write_bytes(weights)
        config = {"model_version": "fixture-1", "preprocessing_version": PREPROCESSING_VERSION,
            "task": "ct_general", "modality": "CT", "anatomy": "CHEST", "protocol_name": "P1",
            "diagnostic_task": "synthetic", "weights_file": "model.onnx",
            "weights_sha256": hashlib.sha256(weights).hexdigest(), "input_size": [16, 16],
            "labels": [{"code": "SYN", "description": "synthetic", "threshold": 0.5}], "limitations": []}
        write_json(artifact / "model.json", config)
        with self.assertRaisesRegex(ModelError, "no manual approval"):
            LocalONNXBackend(artifact / "model.json").load_model()
        for name in ("metrics.json", "model_card.json", "train_config.json", "split.json"):
            write_json(artifact / name, {})
        approve(artifact, "reviewer", "decision-123")
        self.assertTrue((artifact / "approval.json").is_file())
        write_json(artifact / "metrics.json", {"changed": True})
        with self.assertRaisesRegex(ModelError, "artifact files"):
            LocalONNXBackend(artifact / "model.json").load_model()
        config["model_version"] = "tampered"
        write_json(artifact / "model.json", config)
        with self.assertRaisesRegex(ModelError, "approval does not match"):
            LocalONNXBackend(artifact / "model.json").load_model()


if __name__ == "__main__":
    unittest.main()
