"""Выдать демо-ссылку пациента для эпизода (B6).

Запуск:  python -m scripts.issue_link <episode_id> [--base-url http://127.0.0.1:8763]

Печатает адрес страницы пациента с токеном. Токен показывается один раз: в базе
хранится только его HMAC. В пилоте ссылки выдаёт доставка (B5), скрипт — для демо.
"""
from __future__ import annotations

import argparse
import sys

from app.db.base import utcnow
from app.db.session import session_scope
from app.services.patient_service import issue_link

DEFAULT_BASE_URL = "http://127.0.0.1:8763"
PAGE = "/assets/pilot/index.html#/p/"


def link_url(base_url: str, token: str) -> str:
    return base_url.rstrip("/") + PAGE + token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Выдать демо-ссылку пациента")
    parser.add_argument("episode_id")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args(argv)
    try:
        with session_scope() as session:
            token = issue_link(session, args.episode_id, utcnow())
    except LookupError as exc:
        print(f"Ссылка не выдана: {exc} Проверьте id эпизода.", file=sys.stderr)
        return 1
    print(link_url(args.base_url, token))
    return 0


if __name__ == "__main__":
    sys.exit(main())
