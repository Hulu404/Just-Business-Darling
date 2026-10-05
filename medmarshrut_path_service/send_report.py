import hashlib, hmac, json, time, urllib.request

secret = "shared-secret-1234567890"
payload = {
    "source_service": "medmarshrut_image_service",
    "source_report_id": "integration-job-1",
    "source_report_version": 1,
    "study_type": "mr",
    "study_uid": "1.2.3.4.5",
    "patient_ref": "integration-test-1",
    "anatomy": "BRAIN",
    "protocol_name": "MR_BRAIN",
    "finding_code": "FINDING_X",
    "conclusion": "Integration test conclusion",
    "confidence": 0.5,
    "source_model": "integration-fixture",
    "physician_id": "doctor-integration",
    "confirmed_at": "2026-10-03T12:00:00+00:00",
    "confirmation_status": "confirmed",
}
body = json.dumps(payload, ensure_ascii=False).encode()
timestamp = str(int(time.time()))
signature = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
request = urllib.request.Request(
    "http://127.0.0.1:8765/v1/reports",
    data=body,
    headers={"Content-Type": "application/json", "X-Path-Timestamp": timestamp, "X-Path-Signature": signature},
    method="POST",
)
with urllib.request.urlopen(request) as response:
    print(response.status)
    print(response.read().decode())
