"""Read-only aggregate audit of a local archive; never writes patient-level data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from pydicom import dcmread
from numpy.lib import format as npformat


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(root: Path) -> dict:
    csv_path = root / "overview.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    dicoms = sorted((root / "dicom_dir").glob("*.dcm"))
    tiffs = sorted((root / "tiff_images").glob("*.tif"))
    dicom_names = {p.name for p in dicoms}
    tiff_names = {p.name for p in tiffs}
    ids = [r.get("id", "") for r in rows]
    metadata = []
    decoded = 0
    nonconstant = 0
    read_errors = 0
    study_uids = set()
    series_uids = set()
    sop_uids = set()
    patient_ids = set()
    for path in dicoms:
        try:
            ds = dcmread(path)
            metadata.append(ds)
            study_uids.add(str(getattr(ds, "StudyInstanceUID", "")))
            series_uids.add(str(getattr(ds, "SeriesInstanceUID", "")))
            sop_uids.add(str(getattr(ds, "SOPInstanceUID", "")))
            if getattr(ds, "PatientID", None):
                patient_ids.add(str(ds.PatientID))
            pixels = ds.pixel_array
            decoded += 1
            if pixels.size and np.isfinite(pixels).all() and np.max(pixels) > np.min(pixels):
                nonconstant += 1
        except Exception:
            read_errors += 1
    npz = root / "full_archive.npz"
    arrays = {}
    with zipfile.ZipFile(npz) as archive:
        for name in archive.namelist():
            with archive.open(name) as stream:
                version = npformat.read_magic(stream)
                if version == (1, 0):
                    shape, _, dtype = npformat.read_array_header_1_0(stream)
                else:
                    shape, _, dtype = npformat.read_array_header_2_0(stream)
                arrays[name] = {"shape": list(shape), "dtype": str(dtype),
                                "pickle_required": bool(dtype.hasobject)}
    metric_names = ("sensitivity", "specificity", "precision", "recall", "brier_score", "ece_10_bins",
                    "calibration_bins", "subgroups", "errors_by_study_type", "external_validation")
    return {
        "report_type": "archive_audit_and_model_metrics",
        "status": "model_metrics_not_computable",
        "generated_at": datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds"),
        "source": {"path": str(root), "overview_sha256": sha256(csv_path), "overview_rows": len(rows),
                   "overview_columns": columns, "dicom_count": len(dicoms), "tiff_count": len(tiffs),
                   "npz_sha256": sha256(npz), "npz_arrays": arrays},
        "dataset_metrics": {
            "unique_csv_ids": len(set(ids)),
            "csv_dicom_matches": sum(r.get("dicom_name") in dicom_names for r in rows),
            "csv_tiff_matches": sum(r.get("tiff_name") in tiff_names for r in rows),
            "contrast_counts": dict(sorted(Counter(r.get("Contrast", "") for r in rows).items())),
            "dicom_read_errors": read_errors,
            "dicom_pixel_decode_ok": decoded,
            "dicom_nonconstant_images": nonconstant,
            "dicom_modalities": dict(sorted(Counter(str(getattr(ds, "Modality", "")) for ds in metadata).items())),
            "dicom_anatomy": dict(sorted(Counter(str(getattr(ds, "BodyPartExamined", "")) for ds in metadata).items())),
            "unique_study_uids": len(study_uids), "unique_series_uids": len(series_uids),
            "unique_sop_uids": len(sop_uids), "unique_patient_ids": len(patient_ids),
            "duplicate_sop_uid_images": len(metadata) - len(sop_uids),
            "patient_id_populated": sum(bool(getattr(ds, "PatientID", None)) for ds in metadata),
            "patient_name_populated": sum(bool(getattr(ds, "PatientName", None)) for ds in metadata),
            "institution_name_populated": sum(bool(getattr(ds, "InstitutionName", None)) for ds in metadata),
            "protocol_name_populated": sum(bool(getattr(ds, "ProtocolName", None)) for ds in metadata),
            "protocol_name_missing": sum(not bool(getattr(ds, "ProtocolName", None)) for ds in metadata),
            "diagnostic_label_columns": [],
            "institution_id_column_present": "institution_id" in columns,
        },
        "model": {"run_status": "not_run", "reason": "No approved ONNX artifact was provided or found in the project."},
        "model_metrics": {"evaluated_images": 0, "threshold": None,
                          "confusion_matrix": {k: None for k in ("tp", "tn", "fp", "fn")},
                          **{k: None for k in metric_names},
                          "unavailable_reason": "No reference finding labels or predictions from an approved image model; no patient/site-disjoint evaluation manifest."},
        "data_limitations": [
            "Contrast is acquisition metadata, not a diagnostic finding label.",
            "The CSV contains source paths and ages; DICOM identity tags are present. De-identification must be verified before training or sharing.",
            "The NPZ image array has object dtype and requires pickle; it was not deserialized. The DICOM files were audited directly.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
