"""Токен личной ссылки пациента (B6).

Токен показывается один раз при выдаче; в базе — только HMAC-SHA256 от него
с секретом `patient_link_secret`. По утёкшей базе ссылку не восстановить.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from app.config import get_settings

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    secret = get_settings().patient_link_secret.encode()
    return hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()


def looks_like_token(value: str | None) -> bool:
    return value is not None and TOKEN_PATTERN.fullmatch(value) is not None
