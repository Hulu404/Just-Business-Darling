"""Демо-данные и создание таблиц.

Запуск:  python -m scripts.seed_demo

Что делает:
  1) накатывает миграции (если таблиц ещё нет) — через alembic API;
  2) создаёт пилотную клинику, филиал, двух врачей, форматы, цели;
  3) идемпотентно: повторный запуск ничего не дублирует.

Почему клиника нужна заранее: приём события (B2) ищет активную клинику, к
которой привязывать филиалы, врачей и пациентов. Без неё первый же вебхук
вернёт понятную ошибку с подсказкой запустить этот скрипт.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.models import Clinic, Doctor, Format, Goal
from app.db.session import engine, session_scope

ROOT = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    """Накатить миграции. Так таблицы создаются ровно по схеме, а не «как получится»."""
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


def seed() -> None:
    with session_scope() as session:
        clinic = session.query(Clinic).first()
        if clinic is None:
            clinic = Clinic(name="Пилотная клиника", service_enabled=True,
                            theme='{"logo": null, "accent": "#2F6FED", "title": "Клиника"}')
            session.add(clinic)
            session.flush()

        if not session.query(Doctor).filter_by(clinic_id=clinic.id).first():
            session.add_all([
                Doctor(clinic_id=clinic.id, external_id="doc-1",
                       full_name="Иванова Анна Петровна", specialty="Терапевт"),
                Doctor(clinic_id=clinic.id, external_id="doc-2",
                       full_name="Петров Сергей Иванович", specialty="Кардиолог"),
            ])

        if not session.query(Format).filter_by(clinic_id=clinic.id).first():
            session.add_all([
                Format(clinic_id=clinic.id, title="Приём терапевта",
                       price_kopecks=250000, payment_url="https://example-clinic.ru/pay/1"),
                Format(clinic_id=clinic.id, title="Приём кардиолога",
                       price_kopecks=350000, payment_url="https://example-clinic.ru/pay/2"),
            ])

        if not session.query(Goal).filter_by(clinic_id=clinic.id).first():
            session.add_all([
                Goal(clinic_id=clinic.id, title="Обсудить результат с врачом", sort_order=1),
                Goal(clinic_id=clinic.id, title="Повторный анализ через время", sort_order=2),
                Goal(clinic_id=clinic.id, title="Контрольный приём", sort_order=3),
                Goal(clinic_id=clinic.id, title="Другое", sort_order=4),
            ])


def main() -> None:
    print("Накатываю миграции...")
    run_migrations()
    print("Пишу демо-данные...")
    seed()
    print("Готово. Таблиц в базе:", len(engine.dialect.get_table_names(engine.connect())))


if __name__ == "__main__":
    main()
