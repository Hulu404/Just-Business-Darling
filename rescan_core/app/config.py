"""Единый источник настроек.

Всё читается из переменных окружения (и .env в локальной разработке).
Секретов в коде нет: здесь только dev-дефолты, чтобы поднимались тесты.
В проде КАЖДЫЙ секрет задаётся из секрет-хранилища, дефолты не используются.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StaffToken(BaseSettings):
    """Кто стоит за служебным токеном (роль + идентификатор для аудита)."""

    role: str
    actor_id: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: str = "local"
    log_level: str = "INFO"

    # --- PostgreSQL ---
    # В проде — обязательно хост в РФ. SQLite поддерживается для тестов.
    database_url: str = "sqlite+pysqlite:///:memory:"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- B2: подпись вебхуков МИС ---
    mis_hmac_secret: str = "dev-only-change-me"  # noqa: S105
    mis_signature_ttl_seconds: int = Field(default=300, gt=0)
    mis_clinic_id: str | None = None

    # --- B3: группы ---
    pilot_salt: str = "dev-pilot-salt"  # noqa: S105
    control_percent: int = Field(default=25, ge=0, le=100)

    # --- B11: защита контактов ---
    contact_encryption_key: str = "dev-encryption-key-change-me"  # noqa: S105
    contact_hash_salt: str = "dev-hash-salt"  # noqa: S105

    # --- Роли / служебные токены (dev). JSON в env. ---
    staff_tokens: dict[str, StaffToken] = {
        "dev-admin-token": StaffToken(role="administrator", actor_id="dev-admin"),
        "dev-doctor-token": StaffToken(role="doctor", actor_id="dev-doctor"),
    }

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @model_validator(mode="after")
    def require_production_secrets(self) -> Self:
        if self.environment in {"local", "test"}:
            return self
        for name in (
            "mis_hmac_secret", "pilot_salt", "contact_encryption_key", "contact_hash_salt",
        ):
            value = getattr(self, name)
            if len(value.strip()) < 32 or value.startswith("dev-"):
                raise ValueError(f"{name}: задайте отдельный секрет длиной от 32 символов")
        if any(len(token.strip()) < 32 or token.startswith("dev-") for token in self.staff_tokens):
            raise ValueError("staff_tokens: замените демонстрационные токены или задайте {}")
        if not self.mis_clinic_id:
            raise ValueError("mis_clinic_id: укажите клинику интеграции")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")


@lru_cache
def get_settings() -> Settings:
    """Один объект настроек на процесс (кэш), чтобы не парсить env каждый раз."""
    return Settings()


def parse_staff_tokens(raw: str) -> dict[str, StaffToken]:
    """Хелпер для CLI/скриптов: разобрать JSON вида {"token": {"role":..,"actor_id":..}}."""
    data = json.loads(raw)
    return {k: StaffToken(**v) for k, v in data.items()}
