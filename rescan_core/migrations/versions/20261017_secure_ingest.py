"""Удалить открытые тела событий и расширить идентификатор аудита.

Revision ID: 20261017_secure_ingest
Revises: 6002de50cf65
"""
import sqlalchemy as sa
from alembic import op

revision = "20261017_secure_ingest"
down_revision = "6002de50cf65"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Тела могут содержать телефон и произвольные поля: сохранять их нельзя.
    op.execute(sa.text("UPDATE events SET raw_payload = NULL WHERE raw_payload IS NOT NULL"))
    with op.batch_alter_table("audit_events") as batch:
        batch.alter_column("entity_id", existing_type=sa.String(64), type_=sa.String(128))


def downgrade() -> None:
    # Не обрезаем уже принятые длинные ID молча. Очистка raw_payload необратима.
    connection = op.get_bind()
    too_long = connection.execute(
        sa.text("SELECT count(*) FROM audit_events WHERE length(entity_id) > 64")
    ).scalar_one()
    if too_long:
        raise RuntimeError("Нельзя сузить entity_id: в аудите есть ID длиннее 64 символов")
    with op.batch_alter_table("audit_events") as batch:
        batch.alter_column("entity_id", existing_type=sa.String(128), type_=sa.String(64))
