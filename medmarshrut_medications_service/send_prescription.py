import hashlib, hmac, json, time, urllib.request

secret = "shared-secret-1234567890"
payload = {
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
body = json.dumps(payload, ensure_ascii=False).encode()
timestamp = str(int(time.time()))
signature = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
request = urllib.request.Request(
    "http://127.0.0.1:8767/v1/prescriptions",
    data=body,
    headers={"Content-Type": "application/json", "X-Path-Timestamp": timestamp, "X-Path-Signature": signature},
    method="POST",
)
with urllib.request.urlopen(request) as response:
    print(response.status)
    print(response.read().decode())
