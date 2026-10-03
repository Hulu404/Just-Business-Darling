"""Local, pinned ONNX model contract."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydicom import dcmread
from preprocessing import PREPROCESSING_VERSION, dicom_tensor


@dataclass(frozen=True)
class TaskConfig:
    name: str
    modality: str
    min_instances: int
    required_views: frozenset[tuple[str, str]] = frozenset()


TASKS = {
    "ct_general": TaskConfig("ct_general", "CT", 2),
    "mr_general": TaskConfig("mr_general", "MR", 2),
    "mg_screening_2d": TaskConfig("mg_screening_2d", "MG", 4,
        frozenset({("L", "CC"), ("L", "MLO"), ("R", "CC"), ("R", "MLO")})),
}


class ModelError(Exception):
    pass


class ModelBackend(ABC):
    @abstractmethod
    def load_model(self, model_path: Path | None = None) -> None: ...

    @abstractmethod
    def check_compatibility(self, study: dict[str, Any], task: TaskConfig) -> tuple[bool, str]: ...

    @abstractmethod
    def infer_local(self, study: dict[str, Any], task: TaskConfig, archive: bytes) -> dict[str, Any]: ...


class LocalONNXBackend(ModelBackend):
    """Per-image ONNX score vector; deployment requires independently validated weights."""

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.config: dict[str, Any] | None = None
        self.session = None

    def load_model(self, model_path: Path | None = None) -> None:
        try:
            path = self.config_path.resolve(strict=True)
            c = json.loads(path.read_text(encoding="utf-8"))
            required = {"model_version", "preprocessing_version", "modality", "anatomy",
                        "diagnostic_task", "protocol_name", "task", "weights_file",
                        "weights_sha256", "input_size", "labels", "limitations"}
            if not isinstance(c, dict) or not required <= c.keys():
                raise ModelError("Incomplete model configuration")
            if c["task"] not in TASKS or c["modality"] != TASKS[c["task"]].modality:
                raise ModelError("Model task or modality mismatch")
            for key in ("model_version", "preprocessing_version", "anatomy", "diagnostic_task", "protocol_name"):
                if not isinstance(c[key], str) or not c[key].strip():
                    raise ModelError(f"Invalid {key}")
            if c["preprocessing_version"] != PREPROCESSING_VERSION:
                raise ModelError("Unsupported preprocessing version")
            if c.get("birads_enabled", False):
                raise ModelError("BI-RADS requires separate validation and approved rules")
            size = c["input_size"]
            if not isinstance(size, list) or len(size) != 2 or any(type(x) is not int or not 16 <= x <= 4096 for x in size):
                raise ModelError("Invalid input size")
            labels = c["labels"]
            if not isinstance(labels, list) or not labels or len(labels) > 32:
                raise ModelError("Invalid labels")
            for label in labels:
                if (not isinstance(label, dict) or set(label) != {"code", "description", "threshold"}
                        or not isinstance(label["code"], str) or not label["code"]
                        or not isinstance(label["description"], str) or not label["description"]
                        or not isinstance(label["threshold"], (int, float)) or not 0 < label["threshold"] < 1):
                    raise ModelError("Invalid label configuration")
            if len({x["code"] for x in labels}) != len(labels):
                raise ModelError("Duplicate label codes")
            if c["modality"] == "MG" and any("BI-RADS" in x["description"].upper() for x in labels):
                raise ModelError("BI-RADS requires separate validation and approved rules")
            if not isinstance(c["limitations"], list) or not all(isinstance(x, str) for x in c["limitations"]):
                raise ModelError("Invalid limitations")
            weights = (path.parent / c["weights_file"]).resolve(strict=True)
            if model_path is not None and weights != Path(model_path).resolve(strict=True):
                raise ModelError("Weights path differs from configuration")
            if weights.parent != path.parent or weights.suffix.lower() != ".onnx":
                raise ModelError("Weights must be an ONNX file beside the configuration")
            if hashlib.sha256(weights.read_bytes()).hexdigest() != c["weights_sha256"]:
                raise ModelError("Weights SHA-256 mismatch")
            approval_path = path.parent / "approval.json"
            if not approval_path.is_file():
                raise ModelError("Model version has no manual approval")
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            if (not isinstance(approval, dict) or approval.get("model_version") != c["model_version"]
                    or approval.get("config_sha256") != hashlib.sha256(path.read_bytes()).hexdigest()
                    or not isinstance(approval.get("approved_by"), str)
                    or not approval["approved_by"].strip()
                    or not approval.get("approved_at")):
                raise ModelError("Model approval does not match configuration")
            files = approval.get("files_sha256")
            required_files = {"model.onnx", "model.json", "train_config.json", "split.json", "metrics.json", "model_card.json"}
            if (not isinstance(files, dict) or not required_files <= files.keys()
                    or any(name != Path(name).name or name == "approval.json" for name in files)
                    or any(hashlib.sha256((path.parent / name).read_bytes()).hexdigest() != digest
                           for name, digest in files.items())):
                raise ModelError("Model approval does not match artifact files")
            import onnxruntime as ort
            session = ort.InferenceSession(str(weights), providers=["CPUExecutionProvider"])
            if len(session.get_inputs()) != 1 or len(session.get_outputs()) != 1:
                raise ModelError("Expected one model input and output")
            self.session, self.config = session, c
        except ModelError:
            raise
        except (OSError, ValueError, TypeError, KeyError, ImportError, RuntimeError, MemoryError) as exc:
            raise ModelError(f"Local model load failed: {type(exc).__name__}") from exc

    def check_compatibility(self, study: dict[str, Any], task: TaskConfig) -> tuple[bool, str]:
        c = self.config
        if c is None or self.session is None:
            return False, "Local model is not loaded"
        if (task.name != c["task"] or study["modality"] != c["modality"]
                or study.get("protocol_name") != c["protocol_name"]
                or study.get("anatomy") != c["anatomy"]):
            return False, "No model validated for this modality, anatomy and protocol"
        return True, ""

    def infer_local(self, study: dict[str, Any], task: TaskConfig, archive: bytes) -> dict[str, Any]:
        compatible, reason = self.check_compatibility(study, task)
        if not compatible:
            raise ModelError(reason)
        import numpy as np
        c = self.config
        assert c is not None and self.session is not None
        findings = []
        quality = {"instance_count": study["instance_count"], "pixel_decode_ok": True, "min_dynamic_range": None}
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                ds = dcmread(io.BytesIO(z.read(name)))
                pixels = ds.pixel_array.astype(np.float32)
                dynamic_range = float(np.max(pixels) - np.min(pixels))
                quality["min_dynamic_range"] = (dynamic_range if quality["min_dynamic_range"] is None
                                                else min(dynamic_range, quality["min_dynamic_range"]))
                if dynamic_range <= 0:
                    return {**self._base(quality), "findings": [], "refusal_reason": "Constant intensity image"}
                tensor = dicom_tensor(ds, c["input_size"])
                scores = np.asarray(self.session.run(None, {self.session.get_inputs()[0].name: tensor})[0]).reshape(-1)
                if len(scores) != len(c["labels"]) or not np.all(np.isfinite(scores)) or np.any((scores < 0) | (scores > 1)):
                    raise ModelError("Invalid model output")
                for label, score in zip(c["labels"], scores):
                    if float(score) >= label["threshold"]:
                        location = {"series_uid": str(ds.SeriesInstanceUID), "sop_uid": str(ds.SOPInstanceUID)}
                        if task.modality == "MG":
                            location["projection"] = f"{ds.ImageLaterality}-{ds.ViewPosition}"
                        else:
                            location["slice_index"] = study["series"][location["series_uid"]]["ordered_sop_uids"].index(location["sop_uid"]) + 1
                        findings.append({"code": label["code"], "description": label["description"],
                                         "confidence": round(float(score), 4), "localization": location})
        return {**self._base(quality), "findings": findings, "refusal_reason": None}

    def _base(self, quality: dict) -> dict:
        c = self.config
        assert c is not None
        return {"kind": "model_inference", "backend": "LocalONNXBackend", "model_version": c["model_version"],
                "weights_sha256": c["weights_sha256"], "preprocessing_version": c["preprocessing_version"],
                "modality": c["modality"], "anatomy": c["anatomy"], "diagnostic_task": c["diagnostic_task"],
                "protocol_name": c["protocol_name"], "input_quality": quality, "limitations": c["limitations"]}


class TestBackend(ModelBackend):
    """Connectivity test only; never reads pixels or reports findings."""
    def __init__(self) -> None:
        self.loaded = False

    def load_model(self, model_path: Path | None = None) -> None:
        if model_path is not None:
            raise ValueError("Test backend accepts no model path")
        self.loaded = True

    def check_compatibility(self, study: dict[str, Any], task: TaskConfig) -> tuple[bool, str]:
        return study["modality"] == task.modality, "Modality does not match task"

    def infer_local(self, study: dict[str, Any], task: TaskConfig, archive: bytes) -> dict[str, Any]:
        if not self.loaded:
            raise RuntimeError("Test backend was not loaded")
        return {"kind": "test_only", "backend": "TestBackend", "message":
                "Synthetic pipeline check only; no image analysis or clinical finding."}
