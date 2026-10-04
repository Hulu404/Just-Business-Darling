"""Study intake helpers: manifest from the archive, PNG preview, reasons and conclusion templates for the physician."""
from __future__ import annotations

import io
import zipfile

from errors import GatewayError

# Same limits as medmarshrut_image_service/dicom_ingest.py; checked from ZIP headers before any file is read.
MAX_ARCHIVE = 50 * 1024 * 1024
MAX_UNPACKED = 200 * 1024 * 1024
MAX_FILE = 40 * 1024 * 1024
MAX_FILES = 512
MAX_CONFIRM_BODY = 8192
MAX_CONCLUSION = 3500
EDITED = "Текст черновика изменён врачом"

TASKS = {"ct_general": "КТ", "mr_general": "МРТ", "mg_screening_2d": "Маммография"}
MODALITY_TYPES = {"CT": "ct", "MR": "mr", "MG": "mammography"}
MG_ORDER = ["L-CC", "L-MLO", "R-CC", "R-MLO"]

# Image service reasons (English, prefix match) -> text for the physician. Patients and coordinators never see them.
REASONS = [
    ("No local model backend is configured", "Модель не подключена: исследование описывает врач."),
    ("No supported finding above threshold", "Модель не нашла признаков, на которые её проверяли. Исследование описывает врач."),
    ("Demo stand analyses only studies from the demo kit",
     "Демо-стенд анализирует только учебные исследования: это исследование описывает врач."),
    ("Incomplete series", "Серия неполная: в архиве не все срезы из перечня исследования."),
    ("Unsupported transfer syntax", "Файлы DICOM сжаты. Сервис принимает только несжатые файлы."),
    ("Modality does not match selected task", "Вид исследования в файлах не совпадает с выбранным при загрузке."),
    ("Archive contains an invalid DICOM file", "В архиве есть файл, который не читается как DICOM."),
    ("Archive contains a different study", "В архиве есть снимки другого исследования."),
    ("Missing or unexpected series", "Серии в архиве не совпадают с перечнем исследования."),
    ("Too few slices for CT/MR series", "Слишком мало срезов: для КТ и МРТ нужно не меньше двух."),
    ("Irregular slice spacing", "Неровный шаг срезов: возможно, часть срезов не выгрузилась."),
    ("Duplicate or unordered slice positions", "Срезы повторяются или идут не по порядку."),
    ("Incomplete screening mammography", "Для маммографии нужны четыре проекции: L-CC, L-MLO, R-CC и R-MLO."),
    ("Mammography requires FOR PRESENTATION images", "Для маммографии нужны снимки «для просмотра» (FOR PRESENTATION)."),
    ("Unsupported or missing mammography view/laterality", "У снимков маммографии не указаны проекция или сторона."),
    ("Only original primary images are supported", "Сервис принимает только исходные снимки (ORIGINAL, PRIMARY)."),
    ("Multi-frame images are unsupported", "Многокадровые файлы не поддерживаются."),
    ("Unsupported DICOM SOP class or protocol", "Этот тип снимков сервис не поддерживает."),
    ("Mixed acquisition protocols or anatomy", "В архиве снимки разных протоколов или разных областей."),
    ("Invalid or unreadable ZIP archive", "Архив не читается как ZIP."),
    ("Archive is empty or contains too many files", "Архив пустой или в нём больше 512 файлов."),
    ("Inference failed: Inference timed out", "Модель не успела обработать исследование за 30 секунд."),
    ("Inference failed", "Сбой модели при обработке исследования."),
    ("Model load failed", "Модель не загрузилась при запуске сервиса снимков."),
    ("Insufficient memory for inference", "Сервису снимков не хватило памяти для обработки."),
]
UNKNOWN_REASON = "Сервис снимков отправил исследование на ручное описание. Причина без перевода — см. оригинал."


def reason_text(reason: str | None) -> dict | None:
    """Physician-only explanation of a manual review reason, with the English original."""
    if not reason:
        return None
    text = next((ru for en, ru in REASONS if reason.startswith(en)), UNKNOWN_REASON)
    return {"text": text, "original": reason}


def _reject(message: str) -> GatewayError:
    return GatewayError(400, "invalid_archive", message)


def check_zip_limits(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """The service limits, from the ZIP directory only: nothing is decompressed here."""
    members = archive.infolist()
    if len(members) > MAX_FILES:
        raise _reject("В архиве больше 512 файлов. Загрузите одно исследование без лишних файлов.")
    files = [m for m in members if not m.is_dir()]
    if not files:
        raise _reject("Архив пустой. Выберите ZIP-архив с файлами DICOM.")
    total = 0
    for member in files:
        if member.file_size > MAX_FILE:
            raise _reject("В архиве есть файл больше 40 МиБ. Проверьте, что в архиве только снимки DICOM.")
        total += member.file_size
        if total > MAX_UNPACKED:
            raise _reject("После распаковки архив больше 200 МиБ. Загрузите исследование частями или без лишних файлов.")
    return files


def build_manifest(archive_bytes: bytes, task: str) -> dict:
    """Manifest from the archive itself: Study/Series/SOP Instance UIDs of every readable DICOM header.

    The archive is user input: limits are checked before reading, headers are read without pixels and
    tag values are never logged. Everything else (modality, SOP class, completeness) is the service's check.
    """
    if task not in TASKS:
        raise GatewayError(400, "invalid_input", "Выберите вид исследования: КТ, МРТ или маммография.")
    from pydicom import dcmread
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            files = check_zip_limits(archive)
            studies: set[str] = set()
            series: dict[str, list[str]] = {}
            for member in files:
                if member.flag_bits & 1:
                    continue  # encrypted: the service rejects the archive itself
                with archive.open(member) as stream:
                    data = stream.read(MAX_FILE + 1)
                try:
                    ds = dcmread(io.BytesIO(data), stop_before_pixels=True)
                    study, serie, sop = (str(ds.StudyInstanceUID), str(ds.SeriesInstanceUID), str(ds.SOPInstanceUID))
                except Exception:  # not DICOM or no UIDs: left for the service to report
                    continue
                if not (study and serie and sop):
                    continue
                studies.add(study)
                if len(studies) > 1:
                    raise _reject("В архиве несколько исследований. Загрузите каждое исследование отдельным архивом.")
                series.setdefault(serie, []).append(sop)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, OSError, EOFError):
        raise _reject("Файл не читается как ZIP-архив. Выберите ZIP-архив с файлами DICOM.") from None
    if not studies:
        raise _reject("В архиве нет файлов DICOM. Выберите архив с исследованием в формате DICOM.")
    return {"task": task, "study_uid": studies.pop(), "series": series}


def dicom_to_png(data: bytes) -> bytes:
    """A review preview, not a diagnostic viewer: min-max of the frame to 0–255, MONOCHROME1 inverted."""
    import numpy as np
    from PIL import Image
    from pydicom import dcmread
    ds = dcmread(io.BytesIO(data))
    pixels = ds.pixel_array.astype(np.float64)
    low, high = float(pixels.min()), float(pixels.max())
    scaled = np.zeros_like(pixels) if high == low else (pixels - low) * (255.0 / (high - low))
    if str(getattr(ds, "PhotometricInterpretation", "")) == "MONOCHROME1":
        scaled = 255.0 - scaled
    output = io.BytesIO()
    Image.fromarray(np.clip(np.rint(scaled), 0, 255).astype(np.uint8)).save(output, format="PNG")
    return output.getvalue()


def images(study: dict | None) -> list[dict]:
    """Slices or projections the physician can page through, in reading order."""
    if not study:
        return []
    result = []
    for series_uid, series in (study.get("series") or {}).items():
        if study.get("modality") == "MG":
            projections = series.get("projections") or {}
            for sop, name in sorted(projections.items(), key=lambda x: MG_ORDER.index(x[1]) if x[1] in MG_ORDER else 9):
                result.append({"sop_uid": sop, "series_uid": series_uid, "label": "Проекция " + name})
        else:
            order = series.get("ordered_sop_uids") or []
            for index, sop in enumerate(order, 1):
                result.append({"sop_uid": sop, "series_uid": series_uid, "label": f"Срез {index} из {len(order)}"})
    return result


def place(finding: dict, study: dict | None) -> str:
    loc = finding.get("localization") or {}
    if loc.get("projection"):
        return "Проекция " + str(loc["projection"])
    total = len(((study or {}).get("series") or {}).get(loc.get("series_uid"), {}).get("ordered_sop_uids") or [])
    index = loc.get("slice_index")
    return f"Признак на срезе {index} из {total}" if total else f"Признак на срезе {index}"


def is_demo(job: dict) -> bool:
    return str(((job.get("result") or {}).get("model_version")) or "").startswith("demo-")


def conclusion_templates(job: dict, title: str, demo_texts: dict[str, str]) -> dict[str, str]:
    """Editable starting text per finding code. Never the service's draft lines: they carry scores and UIDs."""
    study = job.get("study")
    result = {}
    for finding in (job.get("result") or {}).get("findings") or []:
        code = finding.get("code")
        if is_demo(job) and code in demo_texts:
            result[code] = demo_texts[code]
        else:
            result[code] = f"{title}.\n{str(finding.get('description', '')).capitalize()}. {place(finding, study)}.\n\nЗаключение: "
    return result


def confirm_body(physician_id: str, conclusion: str, finding_code: str, template: str | None,
                 patient_ref: str | None) -> bytes:
    """Body for POST /v1/review/{id}; physician and patient come from the session and the registry."""
    import json
    body = {"physician_id": physician_id, "conclusion": conclusion,
            "edits": [] if template is not None and conclusion == template else [EDITED], "finding_code": finding_code}
    if patient_ref:
        body["patient_ref"] = patient_ref
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_CONFIRM_BODY:
        raise GatewayError(400, "conclusion_too_long",
                           "Заключение слишком длинное для сервиса снимков (не больше 8192 байт). Сократите текст и подтвердите снова.")
    return data
