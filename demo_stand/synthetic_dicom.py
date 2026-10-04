"""Synthetic demo studies for the stand. Pictures, not scans: no patient tags, no real images."""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (CTImageStorage, MRImageStorage, DigitalXRayImageStorageForPresentation,
                         DigitalMammographyXRayImageStorageForPresentation,
                         ExplicitVRLittleEndian, generate_uid)

SIZE = 256

KINDS = {
    "xr": {"title": "Рентгенография органов грудной клетки", "task": "xr_general", "modality": "DX",
           "body_part": "CHEST", "protocol": "CHEST_PA", "study_type": "xray", "count": 1, "spacing": "0.15"},
    "ct": {"title": "КТ органов грудной клетки", "task": "ct_general", "modality": "CT",
           "body_part": "CHEST", "protocol": "CHEST_STANDARD", "study_type": "ct", "count": 3, "spacing": "0.7"},
    "mr": {"title": "МРТ коленного сустава", "task": "mr_general", "modality": "MR",
           "body_part": "KNEE", "protocol": "MR_KNEE", "study_type": "mr", "count": 3, "spacing": "0.5"},
    "mg": {"title": "Маммография", "task": "mg_screening_2d", "modality": "MG",
           "body_part": "BREAST", "protocol": "MG_SCREENING", "study_type": "mammography", "count": 4, "spacing": "0.1"},
}
MG_VIEWS = [("L", "CC"), ("L", "MLO"), ("R", "CC"), ("R", "MLO")]

# Scripted findings shown to the physician. Codes match demo_stand/rules.demo.json.
FINDINGS = {
    "DEMO_XR_INFILTRATE": {"kind": "xr", "description": "участок уплотнения лёгочной ткани", "projection": "PA"},
    "DEMO_CT_INFILTRATE": {"kind": "ct", "description": "участок уплотнения лёгочной ткани", "slice_index": 2},
    "DEMO_CT_NODULE": {"kind": "ct", "description": "очаг в лёгком", "slice_index": 3},
    "DEMO_MR_MENISCUS": {"kind": "mr", "description": "участок изменённого сигнала в мениске", "slice_index": 2},
    "DEMO_MG_DENSITY": {"kind": "mg", "description": "участок уплотнения ткани", "projection": "L-CC"},
}

# Archive name -> (kind, finding codes). Empty list means "no findings".
KIT = {
    "demo-patient-1": ("xr", ["DEMO_XR_INFILTRATE"]),
    "demo-patient-2": ("mg", ["DEMO_MG_DENSITY"]),
    "demo-patient-3": ("ct", ["DEMO_CT_NODULE"]),
    "demo-patient-4": ("mr", ["DEMO_MR_MENISCUS"]),
    "demo-patient-5": ("xr", ["DEMO_XR_INFILTRATE"]),
    "demo-patient-6": ("ct", ["DEMO_CT_NODULE"]),
    "demo-patient-7": ("ct", []),
    "upload-xr-infiltrate": ("xr", ["DEMO_XR_INFILTRATE"]),
    "upload-ct-infiltrate": ("ct", ["DEMO_CT_INFILTRATE"]),
    "upload-ct-nodule": ("ct", ["DEMO_CT_NODULE"]),
    "upload-ct-clear": ("ct", []),
    "upload-mr-meniscus": ("mr", ["DEMO_MR_MENISCUS"]),
    "upload-mg-density": ("mg", ["DEMO_MG_DENSITY"]),
    "smoke-ct": ("ct", ["DEMO_CT_INFILTRATE"]),
    "smoke-mg": ("mg", ["DEMO_MG_DENSITY"]),
    "smoke-xr": ("xr", ["DEMO_XR_INFILTRATE"]),
}


def picture(kind: str, index: int, variant: int) -> np.ndarray:
    """Gradient with circles: obviously a drawing, never mistaken for an image of a person."""
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32)
    image = 200 + 6 * xx + 3 * yy
    centres = [(80 + 20 * index, 90 + 7 * variant % 60, 30), (170, 150 - 10 * index, 22), (120, 200, 14 + 3 * index)]
    if kind == "mg":
        centres = [(128, 60 + 15 * index, 70), (90 + 10 * variant % 50, 140, 18)]
    for cy, cx, radius in centres:
        image[(yy - cy) ** 2 + (xx - cx) ** 2 <= radius ** 2] += 1200
    return np.clip(image, 0, 4000).astype(np.uint16)


def instance(kind: str, study_uid: str, series_uid: str, sop_uid: str, index: int, variant: int) -> bytes:
    spec = KINDS[kind]
    sop_class = {"CT": CTImageStorage, "MR": MRImageStorage, "DX": DigitalXRayImageStorageForPresentation,
                 "MG": DigitalMammographyXRayImageStorageForPresentation}[spec["modality"]]
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
    ds.Modality = spec["modality"]
    ds.StudyDescription = "DEMO SYNTHETIC STUDY"
    ds.SeriesDescription = "DEMO SYNTHETIC SERIES"
    ds.ImageComments = "Synthetic demo picture, not a patient image"
    ds.ImageType = ["ORIGINAL", "PRIMARY"]
    ds.Rows = ds.Columns = SIZE
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    if kind == "xr":  # projection X-ray: detector spacing, as real DX files usually carry
        ds.ImagerPixelSpacing = [spec["spacing"], spec["spacing"]]
    else:
        ds.PixelSpacing = [spec["spacing"], spec["spacing"]]
    ds.ProtocolName = spec["protocol"]
    ds.BodyPartExamined = spec["body_part"]
    pixels = picture(kind, index, variant)
    if kind == "mg" and MG_VIEWS[index][0] == "R":
        pixels = pixels[:, ::-1].copy()
    ds.PixelData = pixels.tobytes()
    if spec["modality"] in {"CT", "MR"}:
        if spec["modality"] == "CT":
            ds.RescaleSlope = "1"
            ds.RescaleIntercept = "-1024"
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0, 0, 5 * index]
        ds.InstanceNumber = index + 1
    elif kind == "xr":
        ds.ViewPosition = "PA"
        ds.PresentationIntentType = "FOR PRESENTATION"
    else:
        ds.ImageLaterality, ds.ViewPosition = MG_VIEWS[index]
        ds.PresentationIntentType = "FOR PRESENTATION"
    output = io.BytesIO()
    ds.save_as(output, enforce_file_format=True)
    return output.getvalue()


def build_study(kind: str, variant: int = 0) -> tuple[bytes, dict]:
    """Return (zip bytes, manifest) for one synthetic study with fresh UIDs."""
    spec = KINDS[kind]
    study_uid, series_uid = generate_uid(), generate_uid()
    sop_uids = [generate_uid() for _ in range(spec["count"])]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, sop_uid in enumerate(sop_uids):
            archive.writestr(f"image{index + 1}.dcm", instance(kind, study_uid, series_uid, sop_uid, index, variant))
    manifest = {"task": spec["task"], "study_uid": study_uid, "series": {series_uid: sop_uids}}
    return output.getvalue(), manifest


def script_item(code: str) -> dict:
    finding = FINDINGS[code]
    place = {k: finding[k] for k in ("slice_index", "projection") if k in finding}
    return {"code": code, "description": finding["description"], **place}


def write_kit(out_dir: Path) -> dict:
    """Write archives, manifests, index.json (study UID -> scripted findings) and kit.json (catalogue)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index, catalogue = {}, {}
    for variant, (name, (kind, codes)) in enumerate(KIT.items()):
        archive, manifest = build_study(kind, variant)
        (out_dir / f"{name}.zip").write_bytes(archive)
        (out_dir / f"{name}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        index[manifest["study_uid"]] = [script_item(code) for code in codes]
        catalogue[name] = {"kind": kind, "title": KINDS[kind]["title"], "task": KINDS[kind]["task"],
                           "study_type": KINDS[kind]["study_type"], "study_uid": manifest["study_uid"],
                           "archive": f"{name}.zip", "manifest": f"{name}.manifest.json", "findings": codes}
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "kit.json").write_text(json.dumps(catalogue, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalogue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Folder for archives, manifests and index.json")
    args = parser.parse_args()
    catalogue = write_kit(args.out)
    print(f"Учебные исследования: {len(catalogue)} архивов в {args.out}", flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
