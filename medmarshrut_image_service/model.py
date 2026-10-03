"""Local model contract. A real backend must be explicitly installed and validated."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskConfig:
    name: str
    modality: str
    min_instances: int
    required_views: frozenset[tuple[str, str]] = frozenset()


TASKS = {
    "ct_general": TaskConfig("ct_general", "CT", 2),
    "mr_general": TaskConfig("mr_general", "MR", 2),
    "mg_screening_2d": TaskConfig(
        "mg_screening_2d", "MG", 4,
        frozenset({("L", "CC"), ("L", "MLO"), ("R", "CC"), ("R", "MLO")}),
    ),
}


class ModelBackend(ABC):
    @abstractmethod
    def load_model(self, model_path: Path | None = None) -> None:
        """Load local weights and fail closed if unavailable or invalid."""

    @abstractmethod
    def check_compatibility(self, study: dict[str, Any], task: TaskConfig) -> tuple[bool, str]:
        """Check acquisition and model input constraints before inference."""

    @abstractmethod
    def infer_local(self, study: dict[str, Any], task: TaskConfig) -> dict[str, Any]:
        """Run local inference. Return a versioned, clinically validated result."""


class TestBackend(ModelBackend):
    """Connectivity test only: it never reads pixels or reports findings."""

    def __init__(self) -> None:
        self.loaded = False

    def load_model(self, model_path: Path | None = None) -> None:
        if model_path is not None:
            raise ValueError("Test backend accepts no model path")
        self.loaded = True

    def check_compatibility(self, study: dict[str, Any], task: TaskConfig) -> tuple[bool, str]:
        return (study["modality"] == task.modality, "Modality does not match task")

    def infer_local(self, study: dict[str, Any], task: TaskConfig) -> dict[str, Any]:
        if not self.loaded:
            raise RuntimeError("Test backend was not loaded")
        return {"kind": "test_only", "backend": "TestBackend", "message":
                "Synthetic pipeline check only; no image analysis or clinical finding."}
