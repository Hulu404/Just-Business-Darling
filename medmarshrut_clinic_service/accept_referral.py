import json, urllib.request
referral_id = "8e36d0984d564e0aadc1cb0f48819238"
body = json.dumps({"actor": "partner-doctor", "note": "Accepted"}).encode()
request = urllib.request.Request(
    f"http://127.0.0.1:8764/v1/referrals/{referral_id}/accept",
    data=body,
    headers={"Content-Type": "application/json", "Authorization": "Bearer staff-token-partner-123"},
    method="POST",
)
with urllib.request.urlopen(request) as response:
    print(response.status)
    print(response.read().decode())
