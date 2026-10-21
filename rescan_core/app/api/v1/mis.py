"""API v1 (B2): приём событий МИС и загрузка CSV.

Оба маршрута защищены HMAC-подписью. Идемпотентность — по event_id.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.events import CsvUploadResult, IngestResult, ResultsReadyEvent
from app.security.hmac import require_csv_signature, require_mis_signature
from app.services.csv_parser import parse_visits_csv
from app.services.ingest_service import IngestService
from app.services.visit_service import import_visits

router = APIRouter(prefix="/v1/mis", tags=["mis"])


@router.post(
    "/results-ready",
    response_model=IngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Приём события «анализы готовы»",
)
async def results_ready(
    body: bytes = Depends(require_mis_signature),
    session: Session = Depends(get_session),
) -> IngestResult:
    """Принять одно событие. Повтор с тем же event_id → duplicate."""
    try:
        event = ResultsReadyEvent.model_validate(json.loads(body))
    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        # ValidationError содержит входные значения, в том числе телефон.
        raise HTTPException(422, detail="Некорректное событие. Проверьте поля контракта.") from exc

    return IngestService(session).ingest(event)


@router.post(
    "/visits-csv",
    response_model=CsvUploadResult,
    summary="Загрузка выгрузки визитов (CSV)",
)
async def upload_visits_csv(
    content: bytes = Depends(require_csv_signature),
    session: Session = Depends(get_session),
) -> CsvUploadResult:
    """Сохранить новые валидные визиты; повторы не увеличивают accepted."""
    rows, errors = parse_visits_csv(content)
    return CsvUploadResult(accepted=import_visits(session, rows), errors=errors)
