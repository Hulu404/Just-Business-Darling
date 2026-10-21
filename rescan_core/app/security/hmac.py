"""Проверка подписи входящих вебхуков МИС (B2).

Подпись = HMAC-SHA256(timestamp + "." + тело, общий_секрет), hex.
Проверяем и свежесть по timestamp — защита от переиспользования старой подписи.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import File, Header, HTTPException, Request, UploadFile, status

from app.config import get_settings


def compute_signature(body: bytes, secret: str, timestamp: str) -> str:
    """Подписываем время вместе с содержимым, чтобы его нельзя было заменить."""
    message = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_signature(
    *,
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    secret: str,
    ttl_seconds: int,
    now: int | None = None,
) -> None:
    """Проверить подпись и свежесть. Бросает HTTPException при провале."""
    if not signature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing signature")
    if not timestamp:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing timestamp")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad timestamp") from exc

    current = now if now is not None else int(time.time())
    if abs(current - ts) > ttl_seconds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "stale signature")

    expected = compute_signature(body, secret, timestamp)
    if not signature.isascii() or not hmac.compare_digest(expected, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")


async def require_mis_signature(
    request: Request,
    x_rescan_signature: str | None = Header(default=None, alias="X-Rescan-Signature"),
    x_rescan_timestamp: str | None = Header(default=None, alias="X-Rescan-Timestamp"),
) -> bytes:
    """Зависимость FastAPI: читает тело, проверяет подпись, возвращает байты.

    Возвращаем тело, чтобы обработчик не читал его повторно: подпись считается
    по байтам, а не по распарсенному JSON.
    """
    settings = get_settings()
    body = await request.body()
    verify_signature(
        body=body,
        signature=x_rescan_signature,
        timestamp=x_rescan_timestamp,
        secret=settings.mis_hmac_secret,
        ttl_seconds=settings.mis_signature_ttl_seconds,
    )
    return body


async def require_csv_signature(
    file: UploadFile = File(...),
    x_rescan_signature: str | None = Header(default=None, alias="X-Rescan-Signature"),
    x_rescan_timestamp: str | None = Header(default=None, alias="X-Rescan-Timestamp"),
) -> bytes:
    """Подпись содержимого файла, без multipart-обёртки и повторного чтения потока."""
    settings = get_settings()
    content = await file.read()
    verify_signature(
        body=content,
        signature=x_rescan_signature,
        timestamp=x_rescan_timestamp,
        secret=settings.mis_hmac_secret,
        ttl_seconds=settings.mis_signature_ttl_seconds,
    )
    return content
