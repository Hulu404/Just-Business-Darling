"""B5: Транспорт для отправки уведомлений (Telegram / SMS)."""
from __future__ import annotations

import json
import logging
import urllib.request
from app.config import get_settings

logger = logging.getLogger(__name__)

class DeliveryError(Exception):
    """Безопасная ошибка: без текста сообщения и номера телефона."""

def _send_telegram(settings, telegram_id: str, text: str) -> None:
    url = f"{settings.telegram_api_url}{settings.telegram_bot_token}/sendMessage"
    payload = json.dumps({"chat_id": telegram_id, "text": text}).encode()
    headers = {"Content-Type": "application/json"}
    
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as response:
        if not 200 <= response.status < 300:
            raise DeliveryError("Ошибка шлюза Telegram")

def _send_sms(settings, phone: str, text: str) -> None:
    url = settings.sms_api_url
    payload = json.dumps({"phone": phone, "text": text}).encode()
    headers = {"Content-Type": "application/json"}
    
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise DeliveryError("Ошибка шлюза SMS")

def send_notification(phone: str, text: str, telegram_id: str | None = None) -> None:
    """Каскадная отправка: пробуем TG, если падает — шлем SMS (если включено)."""
    settings = get_settings()
    
    # 1. Пытаемся отправить в Telegram
    if telegram_id and settings.telegram_enabled:
        try:
            _send_telegram(settings, telegram_id, text)
            logger.info("Отправка в Telegram (текст скрыт)")
            return 
        except Exception:
            logger.warning("Telegram не доставлен")

    # 2. Fallback на SMS (с проверкой флага!)
    if not settings.sms_fallback_enabled:
        # Если SMS выключено (MVP), кидаем ошибку. 
        # Задача уйдет в ретрай (вдруг пациент сейчас привяжет ТГ)
        logger.warning("SMS выключено в настройках. Сообщение не отправлено.")
        raise DeliveryError("SMS fallback disabled")

    try:
        _send_sms(settings, phone, text)
        logger.info("Отправка в SMS (текст скрыт)")
    except Exception:
        logger.error("Не удалось отправить SMS")
        raise DeliveryError()