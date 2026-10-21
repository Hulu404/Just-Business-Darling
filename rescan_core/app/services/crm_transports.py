"""HTTP-доставка B7. Адреса берутся только из серверных настроек."""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.security.hmac import compute_signature

TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 65536


class DeliveryError(Exception):
    """Безопасная ошибка: без URL, ответа приёмника и данных пациента."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Не пересылаем телефон, подпись и секретный путь другому получателю.
        return None


def http_send(kind: str, target: dict[str, str], payload: dict[str, Any]) -> str | None:
    """Возвращает внешний ID либо None; любая неудача — DeliveryError."""
    url = target["url"]
    if kind == "bitrix24":
        url = url.rstrip("/") + "/crm.lead.add.json"
        window = payload["window"]
        data = {"fields": {
            "TITLE": f"Заявка rescan: {payload['goal']['title']}",
            "PHONE": [{"VALUE": payload["phone"], "VALUE_TYPE": "MOBILE"}],
            "COMMENTS": (
                f"Врач: {payload['doctor']['name']}\n"
                f"Формат: {payload['format']['title']}\n"
                f"Окно: {window['title'] or window['code']}"
            ),
            "SOURCE_DESCRIPTION": "rescan",
        }}
    else:
        data = payload
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if kind != "bitrix24":
        timestamp = str(int(time.time()))
        headers["X-Rescan-Timestamp"] = timestamp
        headers["X-Rescan-Signature"] = compute_signature(raw, target["secret"], timestamp)
    try:
        # URL прошёл проверку конфигурации; редиректы запрещены.
        request = Request(url, data=raw, headers=headers, method="POST")  # noqa: S310
        with build_opener(NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
            if not 200 <= response.status < 300:
                raise DeliveryError()
            content = response.read(MAX_RESPONSE_BYTES + 1)
        if len(content) > MAX_RESPONSE_BYTES:
            raise DeliveryError()
        try:
            result = json.loads(content) if content else {}
        except (ValueError, UnicodeError):
            if kind == "bitrix24":
                raise DeliveryError() from None
            result = {}
        identifier = result.get("result" if kind == "bitrix24" else "crm_request_id") \
            if isinstance(result, dict) else None
        valid_id = (
            isinstance(identifier, (str, int)) and not isinstance(identifier, bool)
            and 0 < len(str(identifier)) <= 128
        )
        if kind == "bitrix24" and not valid_id:
            raise DeliveryError()
        return str(identifier) if valid_id else None
    except HTTPError as exc:
        exc.close()
        raise DeliveryError() from None
    except Exception:
        # Даже исключения urllib могут содержать секретный URL; не переносим их текст.
        raise DeliveryError() from None
