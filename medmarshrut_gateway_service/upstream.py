"""Clients for the image, path and clinic services. Secrets stay here and never reach the browser."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from errors import GatewayError

SERVICE_NAMES = {"image": "сервис снимков", "path": "сервис пути", "clinic": "сервис клиники"}
DEFAULT_URLS = {"image": "http://127.0.0.1:8766", "path": "http://127.0.0.1:8765", "clinic": "http://127.0.0.1:8764"}
DEFAULT_TIMEOUT = 10.0
REF_RE = re.compile(r"[A-Za-z0-9_.-]{2,128}")

# Upstream error texts (English, see docs/api-contracts.md) -> message for a person.
# Codes are inconsistent across services, so the message text decides.
MESSAGES = [
    ("Active referral already exists", "Направление этому партнёру уже есть. Дождитесь решения партнёра или отмените направление во вкладке «Направления»."),
    ("Target clinic is not an active partner", "Клиника не входит в число действующих партнёров. Выберите другую клинику из списка."),
    ("Only active patients can be referred", "Направить можно только активного пациента. Проверьте статус карты в регистратуре."),
    ("Referral must originate from the home clinic", "Направить пациента может только его домашняя клиника."),
    ("Only target clinic can", "Это действие доступно только клинике, которая получила направление."),
    ("Only source clinic can cancel", "Отменить направление может только клиника, которая его отправила."),
    ("Referral cannot be cancelled", "Это направление уже нельзя отменить: партнёр его завершил или отклонил."),
    ("Only home clinic can append anamnesis", "Добавлять записи в анамнез может только домашняя клиника пациента."),
    ("Patient is deceased", "Карта пациента закрыта для новых записей."),
    ("Referral is not proposed", "Решение по направлению уже принято. Обновите страницу."),
    ("Referral must be accepted first", "Сначала примите направление, потом отмечайте его выполненным."),
    ("Earlier plan step is unfinished", "Сначала завершите предыдущий шаг плана."),
    ("Episode is not active", "Маршрут сейчас не активен: он на паузе, на ручном разборе или закрыт. Обновите страницу."),
    ("Confirmed outcome requires an attended visit", "Итог приёма можно внести только после того, как визит отмечен состоявшимся."),
    ("Outcome event id reused", "Этот итог приёма уже записан с другим содержимым. Обновите страницу."),
    ("Step must be one of", "Шаг сейчас в другом состоянии. Обновите страницу и попробуйте снова."),
    ("Study is not awaiting physician confirmation", "Исследование уже подтверждено или не ждёт проверки врача. Обновите страницу."),
    ("Invalid physician confirmation or finding code", "Заключение не принято: проверьте текст и выбранный признак."),
    ("patient_ref already registered", "Пациент с таким псевдонимом уже зарегистрирован."),
    ("Patient record is closed", "Карта пациента закрыта для новых записей."),
    ("Not visible to this clinic", "Карта этого пациента вашей клинике не видна."),
]


def signature(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()


def service_url(value: str | None, service: str) -> str:
    url = (value or DEFAULT_URLS[service]).rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port or parts.path or parts.query:
        raise ValueError(f"{service.upper()}_URL must look like http://127.0.0.1:<port>")
    return url


# ---------- checks before a call: unexpected types can crash a service without a response ----------

def text(value: object, name: str, max_length: int, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise GatewayError(400, "invalid_input", f"Поле «{name}» должно быть непустой строкой до {max_length} символов.")
    return value


def patient_ref(value: object) -> str:
    if not isinstance(value, str) or not REF_RE.fullmatch(value):
        raise GatewayError(400, "invalid_input", "Псевдоним пациента: 2–128 символов, латинские буквы, цифры, «-», «_» и «.».")
    return value


def boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise GatewayError(400, "invalid_input", f"Поле «{name}» должно быть true или false.")
    return value


def human_error(service: str, status: int, body: object) -> GatewayError:
    """Turn an upstream error response into a gateway error; the English original goes to detail."""
    original = body.get("error") if isinstance(body, dict) else None
    original = original if isinstance(original, str) else ""
    name = SERVICE_NAMES[service]
    if status in {400, 409}:
        message = next((ru for en, ru in MESSAGES if en in original), None)
        if message is None:
            message = f"{name.capitalize()} отклонил запрос. Проверьте данные и попробуйте снова."
        return GatewayError(409 if status == 409 else 400, "upstream_rejected", message, original or None)
    if status == 404:
        message = next((ru for en, ru in MESSAGES if en in original), "Не нашли то, что запрошено. Обновите страницу.")
        return GatewayError(404, "not_found", message, original or None)
    if status == 403:
        return GatewayError(502, "upstream_auth",
                            f"Шлюз не смог авторизоваться в сервисе: {name}. Перезапустите стенд командой «python start.py».",
                            original or None)
    return GatewayError(502, "upstream_error", f"{name.capitalize()} ответил ошибкой. Попробуйте ещё раз через минуту.",
                        original or None)


class Upstream:
    def __init__(self, urls: dict[str, str], *, reviewer_token: str, path_admin_token: str, path_mis_token: str,
                 clinic_secret: str, clinic_tokens: dict[str, str], timeout: float = DEFAULT_TIMEOUT):
        self.urls = urls
        self.timeout = timeout
        self._bearer = {"reviewer": reviewer_token, "path_admin": path_admin_token, "path_mis": path_mis_token}
        self._clinic_secret = clinic_secret
        self._clinic_tokens = clinic_tokens

    def clinics_with_staff(self) -> set[str]:
        return set(self._clinic_tokens)

    def request(self, service: str, method: str, route: str, *, body: dict | None = None, raw: bytes | None = None,
                content_type: str | None = None, auth: str | tuple[str, str] | None = None,
                timeout: float | None = None, headers: dict[str, str] | None = None) -> tuple[int, object]:
        """One call. Returns (status, JSON or bytes) for any HTTP answer; a dropped connection raises 502/504."""
        name = SERVICE_NAMES[service]
        data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
        headers = dict(headers or {})
        if data is not None:
            headers["Content-Type"] = content_type or "application/json"
        if auth in self._bearer:
            if not self._bearer[auth]:
                raise GatewayError(503, "role_disabled", "Эта операция на стенде выключена: не задан токен МИС.")
            headers["Authorization"] = "Bearer " + self._bearer[auth]
        elif auth == "clinic_signed":
            stamp = str(int(time.time()))
            headers["X-Path-Timestamp"] = stamp
            headers["X-Path-Signature"] = signature(self._clinic_secret, stamp, data or b"")
        elif isinstance(auth, tuple) and auth[0] == "clinic_staff":
            token = self._clinic_tokens.get(auth[1])
            if not token:
                raise GatewayError(403, "forbidden", "У этой клиники нет доступа к сервису клиники на стенде.")
            headers["Authorization"] = "Bearer " + token
        request = Request(self.urls[service] + route, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout or self.timeout) as response:
                status, payload, kind = response.status, response.read(), response.headers.get("Content-Type", "")
        except HTTPError as exc:
            try:
                status, payload, kind = exc.code, exc.read(), exc.headers.get("Content-Type", "")
            except (OSError, http.client.HTTPException):
                raise GatewayError(502, "upstream_unavailable", f"{name.capitalize()} оборвал соединение. Попробуйте ещё раз.") from None
        except (TimeoutError, socket.timeout):
            raise GatewayError(504, "upstream_timeout", f"{name.capitalize()} не ответил вовремя. Попробуйте ещё раз через минуту.") from None
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise GatewayError(504, "upstream_timeout", f"{name.capitalize()} не ответил вовремя. Попробуйте ещё раз через минуту.") from None
            raise GatewayError(502, "upstream_unavailable",
                               f"{name.capitalize()} недоступен. Проверьте, что стенд запущен (python start.py).") from None
        except (OSError, http.client.HTTPException):
            raise GatewayError(502, "upstream_unavailable", f"{name.capitalize()} оборвал соединение. Попробуйте ещё раз.") from None
        if kind.startswith("application/json"):
            try:
                return status, json.loads(payload or b"{}")
            except ValueError:
                raise GatewayError(502, "upstream_error", f"{name.capitalize()} прислал непонятный ответ.") from None
        return status, payload

    def json(self, service: str, method: str, route: str, *, ok: set[int] = frozenset({200, 201}), **kwargs) -> dict:
        """Call and require a JSON success; anything else becomes a human error."""
        status, body = self.request(service, method, route, **kwargs)
        if status not in ok or not isinstance(body, dict):
            raise human_error(service, status, body)
        return body

    # ---------- concrete calls ----------

    def health(self, service: str) -> dict:
        try:
            status, body = self.request(service, "GET", "/health", timeout=2)
        except GatewayError:
            return {"status": "down"}
        if status != 200 or not isinstance(body, dict) or body.get("status") != "ok":
            return {"status": "down"}
        result = {"status": "up"}
        if "network_version" in body:
            result["network_version"] = body["network_version"]
        return result

    def health_all(self) -> dict:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = dict(zip(SERVICE_NAMES, pool.map(self.health, SERVICE_NAMES)))
        for service, result in results.items():
            result["port"] = urlsplit(self.urls[service]).port
        return results

    def patient_by_ref(self, ref: str) -> dict | None:
        status, body = self.request("clinic", "GET", "/v1/patients/by-ref/" + quote(patient_ref(ref), safe=""),
                                    auth="clinic_signed")
        if status == 404:
            return None
        if status != 200 or not isinstance(body, dict):
            raise human_error("clinic", status, body)
        return body
