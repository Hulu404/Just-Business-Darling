"""De-identified image-level dataset manifest and patient-disjoint partitions."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from model import TASKS

TOKEN = re.compile(r"^[A-Za-z0-9_.-]{2,128}$")
FIELDS = {"study_id", "patient_id", "institution_id", "modality", "anatomy", "protocol_name",
          "study_type", "image_path", "image_sha256", "label", "label_source", "finding_location", "annotation_version"}


def _token(value, name):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValueError(f"Invalid pseudonymous {name}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path, task: dict) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    root = path.parent.resolve()
    rows = []
    images = set()
    studies = {}
    patients = defaultdict(set)
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or set(row) != FIELDS:
                raise ValueError("Wrong fields")
            for key in ("study_id", "patient_id", "institution_id", "annotation_version"):
                _token(row[key], key)
            if row["modality"] != task["modality"] or row["anatomy"] != task["anatomy"] or row["protocol_name"] != task["protocol_name"]:
                raise ValueError("Modality, anatomy or protocol differs from task")
            if not isinstance(row["study_type"], str) or not row["study_type"].strip():
                raise ValueError("Missing study type")
            if type(row["label"]) is not int or row["label"] not in (0, 1):
                raise ValueError("Expected binary image label")
            source = row["label_source"]
            if not isinstance(source, dict) or set(source) != {"kind", "reference"} or source["kind"] not in {"expert", "pathology", "follow_up", "registry"}:
                raise ValueError("Invalid label source")
            _token(source["reference"], "label source reference")
            location = row["finding_location"]
            if not isinstance(location, dict) or set(location) != {"series_uid", "sop_uid", "region"}:
                raise ValueError("Invalid finding location")
            _token(location["series_uid"], "series UID")
            _token(location["sop_uid"], "SOP UID")
            if not isinstance(location["region"], str) or not location["region"].strip():
                raise ValueError("Missing region; use 'none' for negatives")
            if row["label"] == 0 and location["region"] != "none":
                raise ValueError("Negative image must have region 'none'")
            if row["label"] == 1 and location["region"] == "none":
                raise ValueError("Positive image needs localization")
            relative = Path(row["image_path"])
            image = (root / relative).resolve()
            if relative.is_absolute() or root not in image.parents or image.suffix.lower() != ".dcm" or not image.is_file():
                raise ValueError("Image must be an existing DICOM below manifest directory")
            if (not isinstance(row["image_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["image_sha256"])
                    or _file_sha256(image) != row["image_sha256"]):
                raise ValueError("Image SHA-256 mismatch")
            key = (row["study_id"], location["sop_uid"])
            if key in images:
                raise ValueError("Duplicate study/image")
            images.add(key)
            identity = (row["patient_id"], row["institution_id"])
            if row["study_id"] in studies and studies[row["study_id"]] != identity:
                raise ValueError("Study identity changes between rows")
            studies[row["study_id"]] = identity
            patients[row["patient_id"]].add(row["institution_id"])
            row["_image"] = str(image)
            rows.append(row)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"Manifest line {line_number}: {exc}") from exc
    if not rows:
        raise ValueError("Empty manifest")
    if any(len(sites) != 1 for sites in patients.values()):
        raise ValueError("Patient occurs in multiple institutions; resolve linkage before split")
    return rows, digest


def split_patients(rows: list[dict], seed: int, external_institution: str) -> dict[str, list[str]]:
    sites = {r["institution_id"] for r in rows}
    if external_institution not in sites or len(sites) < 2:
        raise ValueError("External institution must be present and distinct")
    external = {r["patient_id"] for r in rows if r["institution_id"] == external_institution}
    internal = {r["patient_id"] for r in rows} - external
    if len(internal) < 3:
        raise ValueError("At least three internal patients are needed")
    ordered = sorted(internal, key=lambda p: hashlib.sha256(f"{seed}:{p}".encode()).hexdigest())
    n_test = max(1, round(len(ordered) * .2))
    n_val = max(1, round(len(ordered) * .2))
    if len(ordered) - n_test - n_val < 1:
        raise ValueError("No training patients remain")
    return {"train": ordered[:-(n_test+n_val)], "validation": ordered[-(n_test+n_val):-n_test],
            "test": ordered[-n_test:], "external": sorted(external)}


def validate_split(rows: list[dict], split: dict, digest: str) -> None:
    if split.get("manifest_sha256") != digest:
        raise ValueError("Split is for another manifest revision")
    parts = split.get("patients")
    if not isinstance(parts, dict) or set(parts) != {"train", "validation", "test", "external"}:
        raise ValueError("Missing split partitions")
    seen = set()
    for name, ids in parts.items():
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or seen.intersection(ids):
            raise ValueError(f"Empty or overlapping {name} patients")
        seen.update(ids)
    if seen != {r["patient_id"] for r in rows}:
        raise ValueError("Split does not cover manifest patients")
    external_site = split.get("external_institution")
    if any((r["patient_id"] in parts["external"]) != (r["institution_id"] == external_site) for r in rows):
        raise ValueError("External partition must contain exactly its institution")


def partition(rows: list[dict], split: dict, name: str) -> list[dict]:
    ids = set(split["patients"][name])
    return [r for r in rows if r["patient_id"] in ids]
