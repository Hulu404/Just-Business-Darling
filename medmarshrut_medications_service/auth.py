"""HMAC authentication for inter-service requests."""
from __future__ import annotations

import hashlib
import hmac
import re
import time


def signature(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, provided: str, body: bytes, *, current_time: int | None = None) -> bool:
    if not secret or not re.fullmatch(r"[0-9]{10,12}", timestamp) or not re.fullmatch(r"sha256=[0-9a-f]{64}", provided):
        return False
    current = int(time.time()) if current_time is None else current_time
    if abs(current - int(timestamp)) > 300:
        return False
    return hmac.compare_digest(provided, signature(secret, timestamp, body))