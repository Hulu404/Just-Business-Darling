import hashlib, hmac, json, time, urllib.request

body = json.dumps({
    "event_id": "evt-manual-1",
    "branch_id": "br-1",
    "patient_token": "pt-manual-1",
    "phone": "+79001234567",
    "ordering_doctor_id": "doc-1",
    "ready_at": "2026-10-14T09:00:00+03:00",
    "marketing_consent": True,
}).encode()

sig = hmac.new(b"dev-only-change-me", body, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    "http://127.0.0.1:8000/v1/mis/results-ready", data=body,
    headers={"X-Rescan-Signature": sig,
             "X-Rescan-Timestamp": str(int(time.time())),
             "Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode())