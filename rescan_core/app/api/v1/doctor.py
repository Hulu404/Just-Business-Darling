"""API v1 (B4): очередь врача.

Только роль `doctor`. Врач — запись `doctors` с `external_id = actor_id`
в клинике интеграции. Отметка — по одному эпизоду, массовой отметки нет.
"""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.session import get_session
from app.schemas.queue import (
    QueueResponse,
    StepMarkRequest,
    StepMarkResult,
    StepOptionsResponse,
)
from app.security.roles import Role, require_roles
from app.services.queue_service import QueueService

INVALID_BODY = "Некорректная отметка шага. Проверьте поля запроса."


class AnonymousValidationRoute(APIRoute):
    """422 без `detail[].input`: тело запроса может содержать ПДн."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def anonymous_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse({"detail": INVALID_BODY}, status_code=422)

        return anonymous_handler


router = APIRouter(prefix="/v1/doctor", tags=["doctor"], route_class=AnonymousValidationRoute)
require_doctor = require_roles(Role.DOCTOR)


@router.get("/queue", response_model=QueueResponse, summary="Очередь врача")
def queue(
    staff: tuple[Role, str] = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> QueueResponse:
    """Эпизоды врача, ждущие отметки, по сроку. Без телефона и ФИО."""
    return QueueService(session).queue(staff[1], now=utcnow())


@router.get(
    "/step-options",
    response_model=StepOptionsResponse,
    response_model_exclude_none=True,
    summary="Шаги, включённые клиникой",
)
def step_options(
    staff: tuple[Role, str] = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> StepOptionsResponse:
    return QueueService(session).step_options(staff[1])


@router.post(
    "/episodes/{episode_id}/step",
    response_model=StepMarkResult,
    status_code=status.HTTP_201_CREATED,
    summary="Отметить шаг по одному эпизоду",
)
def mark_step(
    episode_id: str,
    body: StepMarkRequest,
    staff: tuple[Role, str] = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> StepMarkResult:
    """404 — эпизода нет или он чужой; 409 — уже отмечен или срок прошёл."""
    return QueueService(session).mark_step(staff[1], episode_id, body, now=utcnow())
