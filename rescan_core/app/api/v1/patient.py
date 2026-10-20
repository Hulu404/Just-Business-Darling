"""API v1 (B6): страница пациента по личной ссылке.

Токен ссылки — только в заголовке `X-Patient-Link`. Ошибки — `{"detail": {"code",
"message"}}`; 422 обезличен: тело запроса в ответ не возвращается.
"""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.session import get_session
from app.schemas.patient import (
    ChoiceRequest,
    DoctorsResponse,
    FormatsResponse,
    OkResponse,
    RequestCreate,
    RequestCreated,
    SessionResponse,
)
from app.services.patient_service import MESSAGES, PatientService


class PatientValidationRoute(APIRoute):
    """422 `invalid_input` без `detail[].input`: в теле могут быть ПДн."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def anonymous_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                detail = {"code": "invalid_input", "message": MESSAGES["invalid_input"]}
                return JSONResponse({"detail": detail}, status_code=422)

        return anonymous_handler


router = APIRouter(prefix="/v1/patient", tags=["patient"], route_class=PatientValidationRoute)


def link_token(x_patient_link: str | None = Header(None),
               session: Session = Depends(get_session)) -> str | None:
    """Ссылку проверяем зависимостью: 404 раньше разбора тела, ответ одинаковый для всех."""
    PatientService(session).check_link(x_patient_link)
    return x_patient_link


@router.get("/session", response_model=SessionResponse, response_model_exclude_unset=True,
            summary="Состояние страницы пациента")
def patient_session(token: str | None = Depends(link_token),
                    session: Session = Depends(get_session)) -> SessionResponse:
    return PatientService(session).session_info(token, now=utcnow())


@router.post("/consent", response_model=OkResponse, summary="Согласие на обработку данных")
def consent(token: str | None = Depends(link_token),
            session: Session = Depends(get_session)) -> OkResponse:
    return PatientService(session).consent(token, now=utcnow())


@router.post("/choice", response_model=OkResponse, summary="Ветка и цель визита")
def choice(body: ChoiceRequest, token: str | None = Depends(link_token),
           session: Session = Depends(get_session)) -> OkResponse:
    return PatientService(session).choose(token, body, now=utcnow())


@router.get("/doctors", response_model=DoctorsResponse, summary="Врачи для выбранной цели")
def doctors(token: str | None = Depends(link_token),
            session: Session = Depends(get_session)) -> DoctorsResponse:
    return PatientService(session).doctors(token, now=utcnow())


@router.get("/formats", response_model=FormatsResponse, summary="Форматы приёма и окна")
def formats(token: str | None = Depends(link_token),
            session: Session = Depends(get_session)) -> FormatsResponse:
    return PatientService(session).formats(token, now=utcnow())


@router.post("/requests", response_model=RequestCreated, status_code=status.HTTP_201_CREATED,
             summary="Оставить заявку")
def create_request(body: RequestCreate, token: str | None = Depends(link_token),
                   session: Session = Depends(get_session)) -> RequestCreated:
    return PatientService(session).create_request(token, body, now=utcnow())
