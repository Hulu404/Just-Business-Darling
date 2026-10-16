"""Защита контактов (B11): шифрование телефона и его хэш.

Телефон никогда не хранится открытым:
  * encrypt_phone() — кладём в contacts.phone_enc (Fernet, симметрично);
  * hash_phone()    — кладём в contacts.phone_hash (детерминированный хэш для поиска).

Почему два механизма: шифр нельзя искать (он рандомизирован), а хэш нельзя
расшифровать. Хэш — для «найти пациента по номеру», шифр — для «отправить SMS».
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet

from app.config import get_settings

settings = get_settings()


def _fernet() -> Fernet:
    """Ключ приводим к 32 байтам base64url — из произвольной строки в .env."""
    key = settings.contact_encryption_key.encode()
    digest = hashlib.sha256(key).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_phone(phone: str) -> str:
    return _fernet().encrypt(phone.encode()).decode()


def decrypt_phone(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def hash_phone(phone: str) -> str:
    """HMAC-SHA256 от номера с солью — стабильный ключ поиска/дедупа."""
    return hmac.new(
        settings.contact_hash_salt.encode(),
        phone.encode(),
        hashlib.sha256,
    ).hexdigest()
