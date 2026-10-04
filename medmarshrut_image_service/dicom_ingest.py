"""Bounded ZIP intake and conservative DICOM series validation."""

from __future__ import annotations

import io
import json
import math
import re
import zipfile
from collections import defaultdict
from pathlib import PurePosixPath

from pydicom import dcmread
from pydicom.errors import InvalidDicomError
from pydicom.uid import (CTImageStorage, MRImageStorage, DigitalMammographyXRayImageStorageForPresentation,
                         ComputedRadiographyImageStorage, DigitalXRayImageStorageForPresentation)

from model import TASKS, XRAY_MODALITIES, TaskConfig


MAX_ARCHIVE = 50 * 1024 * 1024
MAX_UNPACKED = 200 * 1024 * 1024
MAX_FILE = 40 * 1024 * 1024
MAX_FILES = 512
UID_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")
SOP = {"CT": str(CTImageStorage), "MR": str(MRImageStorage),
       "MG": str(DigitalMammographyXRayImageStorageForPresentation),
       "CR": str(ComputedRadiographyImageStorage), "DX": str(DigitalXRayImageStorageForPresentation)}
XRAY_FRONTAL = {"PA", "AP"}
XRAY_LATERAL = {"LL", "RL", "LATERAL"}
TRANSFER_SYNTAXES = {"1.2.840.10008.1.2", "1.2.840.10008.1.2.1"}


class IntakeError(Exception):
    """A safe, non identifying reason for manual review."""


def _uid(value: object, label: str) -> str:
    value = str(value or "")
    if len(value) > 64 or not UID_RE.fullmatch(value):
        raise IntakeError(f"Missing or invalid {label}")
    return value


def _number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise IntakeError(f"Missing or invalid {label}") from None
    if not math.isfinite(number):
        raise IntakeError(f"Missing or invalid {label}")
    return number


def _vector(value: object, length: int, label: str) -> tuple[float, ...]:
    if value is None or len(value) != length:
        raise IntakeError(f"Missing or invalid {label}")
    return tuple(_number(item, label) for item in value)


def _close(a: float, b: float, tolerance: float = 1e-3) -> bool:
    return abs(a - b) <= tolerance


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def parse_manifest(raw: str) -> dict:
    if len(raw) > 65536:
        raise IntakeError("Manifest exceeds 64 KiB")
    try:
        manifest = json.loads(raw)
    except (TypeError, ValueError):
        raise IntakeError("Invalid manifest JSON") from None
    if not isinstance(manifest, dict) or set(manifest) != {"task", "study_uid", "series"}:
        raise IntakeError("Manifest requires task, study_uid and series")
    if not isinstance(manifest["task"], str) or manifest["task"] not in TASKS:
        raise IntakeError("Unsupported task or protocol")
    _uid(manifest["study_uid"], "study_uid")
    series = manifest["series"]
    if not isinstance(series, dict) or not series or len(series) > 32:
        raise IntakeError("Manifest requires 1–32 series")
    total = 0
    for series_uid, sop_uids in series.items():
        _uid(series_uid, "series_uid")
        if not isinstance(sop_uids, list) or not sop_uids or len(sop_uids) > MAX_FILES:
            raise IntakeError("Each series needs expected SOP Instance UIDs")
        for sop_uid in sop_uids:
            _uid(sop_uid, "SOP Instance UID")
        if len(set(sop_uids)) != len(sop_uids):
            raise IntakeError("Duplicate expected SOP Instance UID")
        total += len(sop_uids)
    if total > MAX_FILES or len({x for uids in series.values() for x in uids}) != total:
        raise IntakeError("Duplicate or excessive expected instances")
    return manifest


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if not members or len(members) > MAX_FILES:
        raise IntakeError("Archive is empty or contains too many files")
    total = 0
    for member in members:
        name = member.filename
        path = PurePosixPath(name)
        if (not name or "\\" in name or ":" in name or name.startswith("/")
                or any(part in {"", ".", ".."} for part in path.parts)
                or (member.external_attr >> 16) & 0o170000 == 0o120000):
            raise IntakeError("Unsafe archive entry path or link")
        if member.is_dir():
            continue
        if member.flag_bits & 1:
            raise IntakeError("Encrypted archive entries are unsupported")
        if member.file_size > MAX_FILE or member.compress_size > MAX_ARCHIVE:
            raise IntakeError("Archive entry exceeds size limit")
        total += member.file_size
        if total > MAX_UNPACKED:
            raise IntakeError("Unpacked archive exceeds size limit")
    return members


def _read_instance(data: bytes, task: TaskConfig) -> dict:
    try:
        ds = dcmread(io.BytesIO(data), force=False)
    except (InvalidDicomError, ValueError, EOFError, OSError):
        raise IntakeError("Archive contains an invalid DICOM file") from None
    modality = str(getattr(ds, "Modality", ""))
    if modality not in task.modalities:
        raise IntakeError("Modality does not match selected task")
    if str(getattr(ds, "SOPClassUID", "")) != SOP[modality]:
        raise IntakeError("Unsupported DICOM SOP class or protocol")
    if str(getattr(ds.file_meta, "TransferSyntaxUID", "")) not in TRANSFER_SYNTAXES:
        raise IntakeError("Unsupported transfer syntax; uncompressed little endian required")
    if str(getattr(ds.file_meta, "MediaStorageSOPInstanceUID", "")) != str(getattr(ds, "SOPInstanceUID", "")):
        raise IntakeError("File meta and dataset SOP Instance UIDs differ")
    if str(getattr(ds.file_meta, "MediaStorageSOPClassUID", "")) != SOP[modality]:
        raise IntakeError("File meta and dataset SOP classes differ")
    study_uid = _uid(getattr(ds, "StudyInstanceUID", None), "StudyInstanceUID")
    series_uid = _uid(getattr(ds, "SeriesInstanceUID", None), "SeriesInstanceUID")
    sop_uid = _uid(getattr(ds, "SOPInstanceUID", None), "SOPInstanceUID")
    image_type = [str(x).upper() for x in getattr(ds, "ImageType", [])]
    if len(image_type) < 2 or image_type[:2] != ["ORIGINAL", "PRIMARY"]:
        raise IntakeError("Only original primary images are supported")
    if int(getattr(ds, "NumberOfFrames", 1)) != 1:
        raise IntakeError("Multi-frame images are unsupported")
    try:
        rows, columns = int(ds.Rows), int(ds.Columns)
        bits, samples = int(ds.BitsAllocated), int(ds.SamplesPerPixel)
        stored = int(ds.BitsStored)
        high_bit, pixel_representation = int(ds.HighBit), int(ds.PixelRepresentation)
    except (AttributeError, TypeError, ValueError):
        raise IntakeError("Missing pixel dimensions or encoding metadata") from None
    if not (1 <= rows <= 8192 and 1 <= columns <= 8192 and bits in {8, 16} and
            1 <= stored <= bits and high_bit == stored - 1 and pixel_representation in {0, 1}
            and samples == 1 and str(getattr(ds, "PhotometricInterpretation", "")) in {"MONOCHROME1", "MONOCHROME2"}):
        raise IntakeError("Unsupported pixel dimensions or encoding")
    if "PixelData" not in ds or len(ds.PixelData) != rows * columns * bits // 8 + (rows * columns * bits // 8) % 2:
        raise IntakeError("Missing or incomplete pixel data")
    raw_spacing = getattr(ds, "PixelSpacing", None)
    if raw_spacing is None and modality in XRAY_MODALITIES:  # projection X-ray often has only the detector spacing
        raw_spacing = getattr(ds, "ImagerPixelSpacing", None)
    spacing = _vector(raw_spacing, 2, "PixelSpacing")
    if any(not 0 < x <= 10 for x in spacing):
        raise IntakeError("Invalid pixel spacing")
    item = {"study_uid": study_uid, "series_uid": series_uid, "sop_uid": sop_uid,
            "modality": modality, "rows": rows, "columns": columns, "spacing": spacing}
    # Exact acquisition metadata is part of model selection, never inferred from a task name.
    item["protocol_name"] = str(getattr(ds, "ProtocolName", "")).strip()
    item["anatomy"] = str(getattr(ds, "BodyPartExamined", "")).strip().upper()
    if modality in {"CT", "MR"}:
        if modality == "CT":
            slope = _number(getattr(ds, "RescaleSlope", None), "RescaleSlope")
            _number(getattr(ds, "RescaleIntercept", None), "RescaleIntercept")
            if slope == 0:
                raise IntakeError("Invalid CT rescale slope")
        orientation = _vector(getattr(ds, "ImageOrientationPatient", None), 6, "ImageOrientationPatient")
        position = _vector(getattr(ds, "ImagePositionPatient", None), 3, "ImagePositionPatient")
        a, b = orientation[:3], orientation[3:]
        if not (_close(sum(x*x for x in a), 1) and _close(sum(x*x for x in b), 1)
                and _close(sum(x*y for x, y in zip(a, b)), 0)):
            raise IntakeError("Invalid image orientation")
        try:
            instance_number = int(ds.InstanceNumber)
        except (AttributeError, TypeError, ValueError):
            raise IntakeError("Missing InstanceNumber") from None
        item.update(orientation=orientation, position=position, instance_number=instance_number)
    elif modality in XRAY_MODALITIES:
        view = str(getattr(ds, "ViewPosition", "")).upper()
        if view not in XRAY_FRONTAL | XRAY_LATERAL:
            raise IntakeError("Unsupported or missing X-ray view position")
        if modality == "DX" and str(getattr(ds, "PresentationIntentType", "")) != "FOR PRESENTATION":
            raise IntakeError("Digital X-ray requires FOR PRESENTATION images")
        item.update(view=view)
    else:
        view = str(getattr(ds, "ViewPosition", "")).upper()
        side = str(getattr(ds, "ImageLaterality", "")).upper()
        if view not in {"CC", "MLO"} or side not in {"L", "R"}:
            raise IntakeError("Unsupported or missing mammography view/laterality")
        if str(getattr(ds, "PresentationIntentType", "")) != "FOR PRESENTATION":
            raise IntakeError("Mammography requires FOR PRESENTATION images")
        item.update(view=view, laterality=side)
    return item


def _validate_series(items: list[dict], task: TaskConfig) -> dict:
    first = items[0]
    for item in items[1:]:
        if (item["rows"], item["columns"]) != (first["rows"], first["columns"]):
            raise IntakeError("Inconsistent image dimensions within series")
        if any(not _close(a, b) for a, b in zip(item["spacing"], first["spacing"])):
            raise IntakeError("Inconsistent pixel spacing within series")
    result = {"instance_count": len(items), "rows": first["rows"], "columns": first["columns"],
              "pixel_spacing_mm": first["spacing"]}
    if task.modalities & XRAY_MODALITIES:
        result["views"] = sorted(x["view"] for x in items)
        result["projections"] = {x["sop_uid"]: x["view"] for x in items}
        return result
    if task.modality == "MG":
        views = {(x["laterality"], x["view"]) for x in items}
        if len(views) != len(items):
            raise IntakeError("Duplicate mammography projections")
        result["views"] = sorted([f"{side}-{view}" for side, view in views])
        result["projections"] = {x["sop_uid"]: f"{x['laterality']}-{x['view']}" for x in items}
        return result
    if len(items) < task.min_instances:
        raise IntakeError("Too few slices for CT/MR series")
    orientation = first["orientation"]
    a, b = orientation[:3], orientation[3:]
    normal = _cross(a, b)
    for item in items[1:]:
        if any(not _close(x, y) for x, y in zip(item["orientation"], orientation)):
            raise IntakeError("Inconsistent orientation within series")
    positions = [(sum(x*y for x, y in zip(item["position"], normal)), item)
                 for item in items]
    positions.sort(key=lambda p: p[0])
    gaps = [positions[i+1][0] - positions[i][0] for i in range(len(positions)-1)]
    if min(gaps) <= 1e-3:
        raise IntakeError("Duplicate or unordered slice positions")
    median = sorted(gaps)[len(gaps)//2]
    if any(abs(gap - median) > max(0.1, median * 0.1) for gap in gaps):
        raise IntakeError("Irregular slice spacing; possible missing slice")
    numbers = [x[1]["instance_number"] for x in positions]
    if len(set(numbers)) != len(numbers) or not (numbers == sorted(numbers) or numbers == sorted(numbers, reverse=True)):
        raise IntakeError("Inconsistent slice instance order")
    result["slice_spacing_mm"] = round(median, 4)
    result["ordered_sop_uids"] = [x[1]["sop_uid"] for x in positions]
    return result


def inspect_archive(archive_bytes: bytes, manifest: dict) -> dict:
    if len(archive_bytes) > MAX_ARCHIVE:
        raise IntakeError("Archive exceeds 50 MiB")
    task = TASKS[manifest["task"]]
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = _safe_members(archive)
            groups = defaultdict(list)
            seen = set()
            for member in members:
                if member.is_dir():
                    continue
                with archive.open(member) as stream:
                    data = stream.read(MAX_FILE + 1)
                if len(data) != member.file_size:
                    raise IntakeError("Archive entry size mismatch")
                item = _read_instance(data, task)
                if item["study_uid"] != manifest["study_uid"]:
                    raise IntakeError("Archive contains a different study")
                if item["sop_uid"] in seen:
                    raise IntakeError("Duplicate SOP Instance UID")
                seen.add(item["sop_uid"])
                groups[item["series_uid"]].append(item)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, OSError):
        raise IntakeError("Invalid or unreadable ZIP archive") from None
    if set(groups) != set(manifest["series"]):
        raise IntakeError("Missing or unexpected series")
    summaries = {}
    protocols = {x["protocol_name"] for group in groups.values() for x in group}
    anatomies = {x["anatomy"] for group in groups.values() for x in group}
    if len(protocols) != 1 or len(anatomies) != 1:
        raise IntakeError("Mixed acquisition protocols or anatomy")
    for series_uid, expected in manifest["series"].items():
        actual = {x["sop_uid"] for x in groups[series_uid]}
        if actual != set(expected):
            raise IntakeError("Incomplete series: expected SOP Instance UIDs do not match")
        summaries[series_uid] = _validate_series(groups[series_uid], task)
    if task.modality == "MG":
        views = {(x["laterality"], x["view"]) for series in groups.values() for x in series}
        if views != task.required_views or sum(len(x) for x in groups.values()) != 4:
            raise IntakeError("Incomplete screening mammography: L/R CC and MLO required")
    modalities = {x["modality"] for series in groups.values() for x in series}
    if len(modalities) != 1:
        raise IntakeError("Mixed modalities in one study")
    if task.modalities & XRAY_MODALITIES:
        views = [x["view"] for series in groups.values() for x in series]
        if (sum(v in XRAY_FRONTAL for v in views) != 1 or sum(v in XRAY_LATERAL for v in views) > 1
                or len(views) > 2):
            raise IntakeError("Chest X-ray requires one PA or AP view; one lateral view is optional")
    return {"task": task.name, "modality": modalities.pop(), "study_uid": manifest["study_uid"],
            "protocol_name": next(iter(protocols)), "anatomy": next(iter(anatomies)),
            "series": summaries, "instance_count": len(seen)}
