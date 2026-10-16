"""Тесты подписи вебхуков (B2)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.security.hmac import compute_signature, verify_signature

SECRET = "secret"
BODY = b'{"event_id":"e1"}'


def test_valid_signature_passes():
    sig = compute_signature(BODY, SECRET)
    verify_signature(body=BODY, signature=sig, timestamp="1000",
                     secret=SECRET, ttl_seconds=300, now=1000)


def test_bad_signature_rejected():
    with pytest.raises(HTTPException) as err:
        verify_signature(body=BODY, signature="deadbeef", timestamp="1000",
                         secret=SECRET, ttl_seconds=300, now=1000)
    assert err.value.status_code == 401


def test_stale_timestamp_rejected():
    sig = compute_signature(BODY, SECRET)
    with pytest.raises(HTTPException) as err:
        verify_signature(body=BODY, signature=sig, timestamp="1000",
                         secret=SECRET, ttl_seconds=300, now=9999)
    assert err.value.status_code == 401


def test_missing_signature_rejected():
    with pytest.raises(HTTPException):
        verify_signature(body=BODY, signature=None, timestamp="1000",
                         secret=SECRET, ttl_seconds=300, now=1000)
