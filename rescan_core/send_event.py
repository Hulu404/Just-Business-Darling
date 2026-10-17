import json
import time
import urllib.request

from app.config import get_settings
from app.security.hmac import compute_signature

body = json.dumps({
    "event_id": "evt-manual-1",
    "branch_id": "br-1",
    "patient_token": "pt-manual-1",
    "phone": "+79001234567",
    "ordering_doctor_id": "doc-1",
    "ready_at": "2026-10-14T09:00:00+03:00",
    "marketing_consent": True,
}).encode()

timestamp = str(int(time.time()))
sig = compute_signature(body, get_settings().mis_hmac_secret, timestamp)
req = urllib.request.Request(
    "http://127.0.0.1:8000/v1/mis/results-ready", data=body,
    headers={"X-Rescan-Signature": sig,
             "X-Rescan-Timestamp": timestamp,
             "Content-Type": "application/json"})
print(urllib.request.urlopen(req, timeout=10).read().decode())  # noqa: S310 - fixed loopback URL
