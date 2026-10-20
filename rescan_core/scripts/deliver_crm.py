"""Отправить готовые заявки и уведомления: python -m scripts.deliver_crm."""
from app.db.base import utcnow
from app.db.session import session_scope
from app.services.crm_service import deliver_pending


def main() -> int:
    with session_scope() as session:
        count = deliver_pending(session, utcnow())
    print(f"Обработано задач CRM и уведомлений: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
