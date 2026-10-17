"""Сохранение CSV-визитов с повторяемым ключом импортированной строки."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC

from sqlalchemy.orm import Session

from app.db.models import Visit
from app.db.upsert import insert_unique
from app.repositories.event_repository import ClinicRepository
from app.schemas.events import VisitRow


def import_visits(session: Session, rows: list[VisitRow]) -> int:
    clinic = ClinicRepository(session).integration_clinic()
    accepted = 0
    for row in rows:
        # Старые CSV без смещения трактуются как UTC; новые выгрузки указывают пояс.
        visit_date = row.visit_date
        if visit_date.tzinfo is None:
            visit_date = visit_date.replace(tzinfo=UTC)
        visit_date = visit_date.astimezone(UTC)
        kopecks = int(row.paid_amount * 100) if row.paid_amount is not None else 0
        canonical = json.dumps(
            [row.patient_token, visit_date.isoformat(), kopecks, row.doctor_id],
            ensure_ascii=False, separators=(",", ":"),
        ).encode()
        external_id = "csv:" + hashlib.sha256(canonical).hexdigest()
        _, inserted = insert_unique(
            session, Visit, {"clinic_id": clinic.id, "external_id": external_id},
            patient_token=row.patient_token, visit_date=visit_date,
            paid_kopecks=kopecks, doctor_external_id=row.doctor_id,
        )
        accepted += int(inserted)
    session.commit()
    return accepted
