"""Allowlisted projections of the path service for patient and clinic screens."""
from __future__ import annotations

import logging
from datetime import datetime

from catalog import STUDY_NAMES, STUDY_TYPE_LABELS

log = logging.getLogger(__name__)

MANUAL_REASONS = {
    "rule_not_approved": "Правило ещё не утверждено клиникой: нужен план врача",
    "unknown_finding_code": "Для этой находки в клинике нет правила",
    "no_approved_rule": "Правило для этой находки есть, но не для этого исследования",
    "unsupported_protocol": "Для такого исследования в клинике нет маршрутов",
    "missing_patient_ref": "В заключении не указан пациент",
    "report_revision": "Пришла новая версия заключения: сверьте с прежним обращением",
    "cancel": "Запись отменена",
    "refuse": "Пациент отказался от шага",
    "lost_contact": "Нет связи с пациентом: нужен новый план врача",
}
KNOWN_EPISODE_STATUSES = {"active", "manual_review", "paused", "completed", "closed"}
KNOWN_STEP_STATUSES = {"open", "offered", "confirmed", "attended", "completed", "cancelled", "refused",
                       "lost_contact", "superseded", "closed"}


def study_title(report: dict) -> str:
    """«Рентгенография органов грудной клетки», «КТ» — never the raw study_type code."""
    kind = report.get("study_type")
    return STUDY_NAMES.get((kind, report.get("anatomy"))) or STUDY_TYPE_LABELS.get(kind) or kind or "Исследование"


def reason_text(reason: str | None) -> str:
    if not reason:
        return ""
    if reason not in MANUAL_REASONS:
        log.warning("Unknown path reason: %s", reason)
    return MANUAL_REASONS.get(reason, reason)


def decision_text(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("rule:"):
        return "Правило, версия " + value[5:]
    if value == "source_report":
        return "Заключение по исследованию"
    if value.startswith("physician_revision:"):
        return "Врач изменил план"
    if value.startswith("physician:"):
        return "План врача"
    if ":physician:" in value:
        return "Итог приёма: врач " + value.rsplit(":physician:", 1)[1]
    log.warning("Unknown decision source: %s", value)
    return value


def _step(step: dict, *, patient: bool) -> dict:
    status = step.get("status")
    if status not in KNOWN_STEP_STATUSES:
        log.warning("Unknown path step status: %s", status)
    result = {key: step.get(key) for key in ("id", "position", "kind", "status", "cycle", "due_at", "appointment_at")}
    result["description"] = "Врач уточняет план" if patient and step.get("kind") == "manual_review" else step.get("description")
    if not patient:
        result["decision_source"] = decision_text(step.get("decision_source"))
        result["owner"] = step.get("owner")
        result["stop_reason"] = step.get("stop_reason")
    return result


def patient_episode(raw: dict, explanation: dict | None = None) -> dict:
    status = raw.get("status")
    if status not in KNOWN_EPISODE_STATUSES:
        log.warning("Unknown path episode status: %s", status)
    report = raw.get("source_report") or {}
    result = {key: raw.get(key) for key in ("id", "status", "created_at", "updated_at")}
    result["title"] = study_title(report)
    result["conclusion"] = report.get("conclusion")
    result["explanation"] = explanation if explanation else {
        "seen": "Заключение готово.", "means": "Врач объяснит результат на приёме"}
    result["steps"] = [_step(s, patient=True) for s in raw.get("plan_steps", [])]
    return result


def staff_episode(raw: dict, name: str, *, callback: bool = False) -> dict:
    status = raw.get("status")
    if status not in KNOWN_EPISODE_STATUSES:
        log.warning("Unknown path episode status: %s", status)
    report = raw.get("source_report") or {}
    result = {key: raw.get(key) for key in ("id", "status", "created_at", "updated_at", "rule_version")}
    result["patient_ref"] = report.get("patient_ref")
    result["patient"] = name or "Пациент не указан"
    result["title"] = study_title(report)
    result["reason"] = reason_text(raw.get("manual_reason")) if status in {"manual_review", "paused"} else ""
    result["callback"] = callback
    result["steps"] = [_step(s, patient=False) for s in raw.get("plan_steps", [])]
    result["source_report"] = {key: report.get(key) for key in (
        "source_report_id", "conclusion", "study_type", "anatomy", "protocol_name", "finding_code",
        "physician_id", "confirmed_at", "source_model")}
    result["audit_events"] = [{"event_type": event.get("event_type"), "actor": event.get("actor"),
                               "occurred_at": event.get("occurred_at"), "details": event.get("details")}
                              for event in raw.get("audit_events", [])]
    return result
