"""Upgrade старой БД очищает тела и сохраняет работоспособность схемы."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db.models import Clinic
from app.schemas.events import ResultsReadyEvent
from app.services.ingest_service import IngestService
from tests.test_ingest import EVENT

ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_cleans_existing_payload_and_accepts_long_id(empty_engine):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "6002de50cf65")
        conn.execute(text(
            "INSERT INTO events (id, event_id, patient_token, ready_at, marketing_consent, "
            "raw_payload, created_at, updated_at) VALUES "
            "(:id, :event, :patient, CURRENT_TIMESTAMP, :consent, :raw, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"id": "synthetic-event", "event": "old", "patient": "demo-patient",
            "consent": False, "raw": '{"phone":"+70000000000","extra":"demo"}'})
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        assert conn.execute(text("SELECT raw_payload FROM events")).scalar_one() is None
        columns = {col["name"]: col for col in inspect(conn).get_columns("audit_events")}
        assert columns["entity_id"]["type"].length == 128
    with Session(empty_engine) as session:
        session.add(Clinic(name="Демо после миграции", service_enabled=True))
        session.commit()
        event = ResultsReadyEvent(**{**EVENT, "event_id": "e" * 128})
        result = IngestService(session).ingest(event)
        assert result.status == "created"
