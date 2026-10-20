"""B7: подписанный статус CRM и отметка администратора."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_session
from app.schemas.crm import CrmStatus, ManualStatus, StatusResult
from app.security.hmac import verify_signature
from app.security.roles import Role, require_roles
from app.services.crm_service import change_status


class PrivateValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    {"detail": {"code": "invalid_input",
                                "message": "Некорректный статус заявки. Проверьте поля запроса."}},
                    status_code=422,
                )

        return handle


router = APIRouter(prefix="/v1", tags=["crm"], route_class=PrivateValidationRoute)


async def require_crm_signature(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Rescan-Signature"),
    timestamp: str | None = Header(default=None, alias="X-Rescan-Timestamp"),
) -> None:
    settings = get_settings()
    try:
        verify_signature(
            body=await request.body(), signature=signature, timestamp=timestamp,
            secret=settings.crm_status_secret, ttl_seconds=settings.mis_signature_ttl_seconds,
        )
    except HTTPException:
        raise HTTPException(401, {
            "code": "bad_signature",
            "message": "Подпись не принята. Проверьте подпись и время запроса.",
        }) from None


@router.post("/crm/status", response_model=StatusResult,
             dependencies=[Depends(require_crm_signature)])
def crm_status(body: CrmStatus, session: Session = Depends(get_session)) -> StatusResult:
    return change_status(session, body.status, request_id=body.request_id,
                         crm_request_id=body.crm_request_id, actor_id="crm")


@router.post("/admin/requests/{request_id}/status", response_model=StatusResult)
def manual_status(
    request_id: str, body: ManualStatus,
    staff: tuple[Role, str] = Depends(require_roles(Role.ADMINISTRATOR)),
    session: Session = Depends(get_session),
) -> StatusResult:
    return change_status(session, body.status, request_id=request_id,
                         actor_id=staff[1], manual=True)
