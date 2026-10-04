"""Synthetic prescription -> offers -> order -> pickup flow."""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import time
import urllib.request
from pathlib import Path

from catalog import Catalog
from store import MedStore


def _signed_post(url: str, secret: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload, ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    signature = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(url, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Path-Timestamp": timestamp, "X-Path-Signature": signature})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> None:
    secret = "shared-secret-1234567890"
    base = "http://127.0.0.1:8767"
    prescription = {
        "source_service": "medmarshrut_path_service",
        "source_prescription_id": "rx-demo-1",
        "source_prescription_version": 1,
        "patient_ref": "integration-test-1",
        "physician_id": "doctor-integration",
        "confirmed_at": "2026-10-04T09:00:00+00:00",
        "expires_at": "2026-11-03T09:00:00+00:00",
        "conclusion": "Synthetic conclusion for demo",
        "study_uid": "1.2.3.4.5",
        "items": [
            {"inn": "amoxicillin", "trade_name": "Amoxil", "form": "capsule", "strength": "500 mg",
             "dosage": "1 capsule 3 times daily", "duration_days": 7, "quantity": 21,
             "substitution_allowed": True},
            {"inn": "omeprazole", "trade_name": "Losec", "form": "capsule", "strength": "20 mg",
             "dosage": "1 capsule daily", "duration_days": 14, "quantity": 14,
             "substitution_allowed": False},
        ],
    }
    status, body = _signed_post(base + "/v1/prescriptions", secret, prescription)
    print("ingest:", status, json.dumps(body, ensure_ascii=False))
    pid = body["prescription_id"]

    # offers require admin token in this demo; we call the store directly instead
    print("\nTo see offers, use the patient UI at http://127.0.0.1:8767/patient")
    print(f"prescription_id = {pid}")
    print(f"patient_ref = integration-test-1")


if __name__ == "__main__":
    main()