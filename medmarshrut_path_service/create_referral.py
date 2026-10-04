import hashlib, hmac, json, time, urllib.request

secret = "shared-secret-1234567890"
payload = {
    "patient_ref": "integration-test-1",
    "from_clinic_id": "clinic-central",
    "to_clinic_id": "clinic-partner-1",
    "reason": "Integration test referral",
    "created_by": "doctor-integration",
}
body = json.dumps(payload, ensure_ascii=False).encode()
timestamp = str(int(time.time()))
signature = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
request = urllib.request.Request(
    "http://127.0.0.1:8764/v1/referrals",
    data=body,
    headers={"Content-Type": "application/json", "X-Path-Timestamp": timestamp, "X-Path-Signature": signature},
    method="POST",
)
with urllib.request.urlopen(request) as response:
    print(response.status)
    print(response.read().decode())
