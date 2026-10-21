"""API пациента (B6): ссылки пациента, врачи цели, настройки страницы и выбор пациента.

Revision ID: 20261020_patient_api
Revises: 20261019_doctor_queue
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "20261020_patient_api"
down_revision = "20261019_doctor_queue"
branch_labels = None
depends_on = None

# Старые ключи темы из seed_demo → ключи ответа API пациента.
THEME_KEYS = {"logo": "logo_url", "title": "name"}


def upgrade() -> None:
    op.create_table(
        "patient_links",
        sa.Column("episode_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_patient_link_hash"),
    )
    op.create_index(op.f("ix_patient_links_episode_id"), "patient_links", ["episode_id"])
    op.create_table(
        "goal_doctors",
        sa.Column("goal_id", sa.String(length=36), nullable=False),
        sa.Column("doctor_id", sa.String(length=36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"]),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"]),
        sa.PrimaryKeyConstraint("goal_id", "doctor_id"),
    )
    op.add_column("clinics", sa.Column("patient_settings", sa.Text()))
    op.add_column("episodes", sa.Column("chosen_branch", sa.String(length=16)))
    if op.get_bind().dialect.name == "sqlite":
        # SQLite не добавляет внешний ключ через ALTER; пересоздание таблицы episodes
        # уронило бы базу с дочерними строками при включённых внешних ключах.
        op.execute("ALTER TABLE episodes ADD COLUMN chosen_goal_id VARCHAR(36) "
                   "REFERENCES goals (id)")
    else:
        op.add_column("episodes", sa.Column("chosen_goal_id", sa.String(length=36)))
        op.create_foreign_key("fk_episodes_chosen_goal_id", "episodes", "goals",
                              ["chosen_goal_id"], ["id"])
    _rename_theme_keys(THEME_KEYS)


def downgrade() -> None:
    _rename_theme_keys({new: old for old, new in THEME_KEYS.items()})
    with op.batch_alter_table("episodes") as batch:
        if op.get_bind().dialect.name != "sqlite":
            batch.drop_constraint("fk_episodes_chosen_goal_id", type_="foreignkey")
        batch.drop_column("chosen_goal_id")
        batch.drop_column("chosen_branch")
    op.drop_column("clinics", "patient_settings")
    op.drop_table("goal_doctors")
    op.drop_index(op.f("ix_patient_links_episode_id"), table_name="patient_links")
    op.drop_table("patient_links")


def _rename_theme_keys(mapping: dict[str, str]) -> None:
    """Переименовать ключи темы в существующих строках. Испорченный JSON не трогаем."""
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, theme FROM clinics WHERE theme IS NOT NULL")).all()
    for clinic_id, raw in rows:
        try:
            theme = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(theme, dict):
            continue
        renamed = dict(theme)
        for old, new in mapping.items():
            if old in renamed and new not in renamed:
                renamed[new] = renamed.pop(old)
        if renamed != theme:
            bind.execute(sa.text("UPDATE clinics SET theme = :theme WHERE id = :id"),
                         {"theme": json.dumps(renamed, ensure_ascii=False), "id": clinic_id})
