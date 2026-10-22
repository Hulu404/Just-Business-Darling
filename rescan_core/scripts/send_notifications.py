"""Отправить готовые уведомления (TG/SMS): python -m scripts.send_notifications."""
from app.db.base import utcnow
from app.db.session import session_scope
# ИЗМЕНЕНИЕ 1: Импортируем из нового файла message_service
from app.services.message_service import deliver_pending_messages

def main() -> int:
    with session_scope() as session:
        # ИЗМЕНЕНИЕ 2: Вызываем новую функцию deliver_pending_messages
        count = deliver_pending_messages(session, utcnow())
    # ИЗМЕНЕНИЕ 3: Текст вывода (было "SMS", стало "уведомлений")
    print(f"Обработано уведомлений: {count}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())