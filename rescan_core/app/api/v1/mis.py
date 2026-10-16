"""API v1 (B2): приём событий МИС и загрузка CSV.

Оба маршрута защищены HMAC-подписью. Идемпотентность — по event_id.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.events import CsvUploadResult, IngestResult, ResultsReadyEvent
from app.security.hmac import require_mis_signature
from app.services.csv_parser import parse_visits_csv
from app.services.ingest_service import IngestService

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
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return IngestService(session).ingest(event, raw=body)


@router.post(
    "/visits-csv",
    response_model=CsvUploadResult,
    summary="Загрузка выгрузки визитов (CSV)",
)
async def upload_visits_csv(
    file: UploadFile = File(...),
    _: bytes = Depends(require_mis_signature),
) -> CsvUploadResult:
    """Разобрать CSV визитов. Возвращает число принятых строк и ошибки построчно."""
    content = await file.read()
    rows, errors = parse_visits_csv(content)
    return CsvUploadResult(accepted=len(rows), errors=errors)
