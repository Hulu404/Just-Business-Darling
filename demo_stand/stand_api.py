"""HTTP client for the demo stand scripts. Uses only public service APIs; secrets come from start.py."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

IMAGE = "http://127.0.0.1:8766"
PATH = "http://127.0.0.1:8765"
CLINIC = "http://127.0.0.1:8764"
# start.py passes the gateway address: on Railway the gateway listens on $PORT, not 8763.
GATEWAY = os.environ.get("DEMO_GATEWAY_URL") or "http://127.0.0.1:8763"
DEMO_DIR = Path(__file__).resolve().parent


class StandError(Exception):
    """A failed demo step; the message says what happened."""


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"Не задана переменная окружения {name}. Запустите стенд командой «python start.py»; "
                         f"для ручного запуска возьмите значения из «python start.py --print-secrets».")
    return value


def utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def call(method: str, url: str, body: dict | None = None, *, token: str | None = None,
         secret: str | None = None, raw: bytes | None = None, headers: dict | None = None,
         timeout: float = 15) -> tuple[int, object]:
    """Send one request. Returns (status, parsed JSON or bytes). A dropped connection is a service error."""
    data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
    sent = dict(headers or {})
    if body is not None:
        sent["Content-Type"] = "application/json"
    if token:
        sent["Authorization"] = "Bearer " + token
    if secret:
        stamp = str(int(time.time()))
        sent["X-Path-Timestamp"] = stamp
        sent["X-Path-Signature"] = "sha256=" + hmac.new(secret.encode("utf-8"), stamp.encode("ascii") + b"." + (data or b""),
                                                        hashlib.sha256).hexdigest()
    request = Request(url, data=data, headers=sent, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status, payload, kind = response.status, response.read(), response.headers.get("Content-Type", "")
    except HTTPError as exc:
        status, payload, kind = exc.code, exc.read(), exc.headers.get("Content-Type", "")
    except (URLError, OSError) as exc:
        raise StandError(f"{method} {url}: сервис не ответил ({exc}). Проверьте, что стенд запущен.") from None
    if kind.startswith("application/json"):
        return status, json.loads(payload or b"{}")
    return status, payload


def expect(status: int, body: object, codes: set[int] | int, what: str) -> object:
    codes = {codes} if isinstance(codes, int) else codes
    if status not in codes:
        raise StandError(f"{what}: ожидали {sorted(codes)}, получили {status} {body}")
    return body


# ---------- gateway ----------

class Gateway:
    """A demo-role window of the gateway: the session cookie and X-MM-Role, like the browser sends them."""

    def __init__(self, role: str, **extra):
        self.role = role
        request = Request(GATEWAY + "/api/session", data=json.dumps({"role": role, **extra}).encode("utf-8"),
                          headers={"Content-Type": "application/json", "X-MM-Role": role}, method="POST")
        try:
            with urlopen(request, timeout=15) as response:
                self.cookie = (response.headers.get("Set-Cookie") or "").split(";", 1)[0]
        except HTTPError as exc:
            raise StandError(f"Сессия «{role}» в шлюзе: {exc.code} {exc.read().decode('utf-8', 'replace')}") from None
        except (URLError, OSError) as exc:
            raise StandError(f"Шлюз не ответил ({exc}). Проверьте, что стенд запущен.") from None

    def call(self, method: str, route: str, body: dict | None = None, *, raw: bytes | None = None,
             content_type: str | None = None) -> tuple[int, object]:
        headers = {"X-MM-Role": self.role, "Cookie": self.cookie}
        if content_type:
            headers["Content-Type"] = content_type
        return call(method, GATEWAY + route, body, raw=raw, headers=headers, timeout=70)


# ---------- image service ----------

def upload_study(archive: bytes, manifest: dict) -> tuple[int, dict]:
    return call("POST", IMAGE + "/v1/studies", raw=archive,
                headers={"Content-Type": "application/zip", "X-Study-Manifest": json.dumps(manifest)})


def upload_kit(kit_dir: Path, name: str) -> tuple[int, dict]:
    catalogue = load_json(kit_dir / "kit.json")[name]
    return upload_study((kit_dir / catalogue["archive"]).read_bytes(), load_json(kit_dir / catalogue["manifest"]))


def review(job_id: str) -> dict:
    status, body = call("GET", f"{IMAGE}/v1/review/{job_id}", token=env("REVIEWER_TOKEN"))
    return expect(status, body, 200, "Чтение исследования врачом")


def confirm(job_id: str, physician_id: str, conclusion: str, finding_code: str, patient_ref: str | None) -> dict:
    body = {"physician_id": physician_id, "conclusion": conclusion, "edits": [], "finding_code": finding_code}
    if patient_ref is not None:
        body["patient_ref"] = patient_ref
    status, result = call("POST", f"{IMAGE}/v1/review/{job_id}", body, token=env("REVIEWER_TOKEN"))
    return expect(status, result, 200, "Подтверждение врачом")


# ---------- path service ----------

def path_get(route: str) -> dict:
    status, body = call("GET", PATH + route, token=env("PATH_ADMIN_TOKEN"))
    return expect(status, body, 200, f"GET {route}")


def path_post(route: str, body: dict, codes: set[int] | int = 200) -> dict:
    status, result = call("POST", PATH + route, body, token=env("PATH_ADMIN_TOKEN"))
    return expect(status, result, codes, f"POST {route}")


def find_episode(source_report_id: str) -> dict | None:
    for episode_id in path_get("/v1/episodes")["episode_ids"]:
        episode = path_get(f"/v1/episodes/{episode_id}")
        if episode["source_report"]["source_report_id"] == source_report_id:
            return episode
    return None


def step_action(episode_id: str, step_id: str, action: str, actor: str, evidence: str, **times) -> dict:
    return path_post(f"/v1/episodes/{episode_id}/steps/{step_id}/{action}",
                     {"actor": actor, "evidence": evidence, **times})


# ---------- clinic service ----------

def staff_token(clinic_id: str) -> str:
    tokens = json.loads(env("CLINIC_STAFF_TOKENS"))
    token = next((t for t, c in tokens.items() if c == clinic_id), None)
    if not token:
        raise SystemExit(f"В CLINIC_STAFF_TOKENS нет токена сотрудника для {clinic_id}")
    return token


def clinic_staff(method: str, route: str, clinic_id: str, body: dict | None = None) -> tuple[int, object]:
    return call(method, CLINIC + route, body, token=staff_token(clinic_id))


def clinic_signed(route: str, body: dict) -> tuple[int, object]:
    return call("POST", CLINIC + route, body, secret=env("CLINIC_SHARED_SECRET"))
