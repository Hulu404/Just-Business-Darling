"""Очередь врача (B4): срок отметки эпизода и список шагов клиники.

Revision ID: 20261019_doctor_queue
Revises: 20261017_secure_ingest
"""
import sqlalchemy as sa
from alembic import op

revision = "20261019_doctor_queue"
down_revision = "20261017_secure_ingest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Обе колонки допускают NULL: старые эпизоды в очередь не попадают,
    # а клиника без списка шагов получает 503 до настройки.
    with op.batch_alter_table("episodes") as batch:
        batch.add_column(sa.Column("queue_deadline_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("clinics") as batch:
        batch.add_column(sa.Column("step_options", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("clinics") as batch:
        batch.drop_column("step_options")
    with op.batch_alter_table("episodes") as batch:
        batch.drop_column("queue_deadline_at")
