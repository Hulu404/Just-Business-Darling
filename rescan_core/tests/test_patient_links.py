"""B6: ссылки пациента, настройки и миграция `20261020_patient_api`."""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import inspect, select, text

from app.config import Settings, get_settings
from app.db.models import Clinic, Episode, Patient, PatientLink
from app.security.patient_link import TOKEN_PATTERN, hash_token, looks_like_token, new_token
from app.services.patient_service import issue_link
from tests.test_patient_api import SETTINGS

ROOT = Path(__file__).resolve().parents[1]
B4_REVISION = "20261019_doctor_queue"


def alembic_config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return cfg


def insert_b4_data(conn) -> None:
    """Данные, какие бывают после B4: клиника со старой темой, пациент, эпизод, шаг."""
    conn.execute(text(
        "INSERT INTO clinics (id, name, theme, service_enabled, step_options, created_at, "
        "updated_at) VALUES ('c1', 'Демо', :theme, :on, NULL, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP)"),
        {"on": True, "theme": '{"logo": null, "accent": "#2F6FED", "title": "Клиника"}'})
    conn.execute(text(
        "INSERT INTO clinics (id, name, theme, service_enabled, created_at, updated_at) "
        "VALUES ('c2', 'Демо 2', 'not json', :on, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
        {"on": True})
    conn.execute(text(
        "INSERT INTO patients (id, clinic_id, patient_token, opted_out, created_at, "
        "updated_at) VALUES ('p1', 'c1', 'demo-token', :off, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP)"), {"off": False})
    conn.execute(text(
        "INSERT INTO episodes (id, patient_id, \"group\", status, ready_at, created_at, "
        "updated_at) VALUES ('e1', 'p1', 'main', 'doctor_marked', CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    conn.execute(text(
        "INSERT INTO steps (id, episode_id, kind, status, created_at, updated_at) "
        "VALUES ('s1', 'e1', 'discuss', 'open', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))


def assert_b6_schema(conn) -> None:
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    assert {"patient_links", "goal_doctors"} <= tables
    assert {c["name"] for c in inspector.get_columns("patient_links")} == {
        "id", "episode_id", "token_hash", "expires_at", "revoked_at", "created_at"}
    assert {c["name"] for c in inspector.get_columns("goal_doctors")} == {
        "goal_id", "doctor_id", "sort_order"}
    assert "patient_settings" in {c["name"] for c in inspector.get_columns("clinics")}
    episode_columns = {c["name"] for c in inspector.get_columns("episodes")}
    assert {"chosen_branch", "chosen_goal_id"} <= episode_columns
    fks = inspector.get_foreign_keys("episodes")
    assert any(fk["constrained_columns"] == ["chosen_goal_id"]
               and fk["referred_table"] == "goals" for fk in fks)


def test_migration_on_empty_database(empty_engine):
    cfg = alembic_config()
    with empty_engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        assert_b6_schema(conn)


def test_migration_keeps_b4_data_and_renames_theme_keys(empty_engine):
    cfg = alembic_config()
    with empty_engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, B4_REVISION)
        insert_b4_data(conn)
        command.upgrade(cfg, "head")
        assert_b6_schema(conn)

        theme = json.loads(conn.execute(
            text("SELECT theme FROM clinics WHERE id = 'c1'")).scalar_one())
        assert theme == {"logo_url": None, "accent": "#2F6FED", "name": "Клиника"}
        assert conn.execute(
            text("SELECT theme FROM clinics WHERE id = 'c2'")).scalar_one() == "not json"
        row = conn.execute(text(
            "SELECT status, chosen_branch, chosen_goal_id FROM episodes WHERE id = 'e1'")).one()
        assert tuple(row) == ("doctor_marked", None, None)
        assert conn.execute(text("SELECT kind FROM steps WHERE id = 's1'")).scalar_one() \
            == "discuss"
        assert conn.execute(text("SELECT patient_settings FROM clinics WHERE id = 'c1'")
                            ).scalar_one() is None


@pytest.fixture
def main_episode(db_session) -> Episode:
    clinic = db_session.execute(select(Clinic)).scalar_one()
    patient = Patient(clinic_id=clinic.id, patient_token="pt-link", group="main")
    db_session.add(patient)
    db_session.flush()
    episode = Episode(patient_id=patient.id, group="main", status="awaiting_doctor",
                      ready_at=datetime(2026, 10, 18, tzinfo=UTC))
    db_session.add(episode)
    db_session.commit()
    return episode


def test_new_token_format():
    tokens = {new_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(TOKEN_PATTERN.fullmatch(token) and len(token) >= 40 for token in tokens)


def test_hash_is_hmac_with_link_secret(monkeypatch):
    token = new_token()
    first = hash_token(token)
    assert len(first) == 64 and int(first, 16) >= 0
    assert first == hash_token(token)
    assert first != hashlib.sha256(token.encode()).hexdigest()
    monkeypatch.setattr(get_settings(), "patient_link_secret", "dev-other-secret")
    assert hash_token(token) != first


@pytest.mark.parametrize(("value", "ok"), [
    (None, False), ("", False), ("a" * 15, False), ("a" * 16, True), ("a" * 128, True),
    ("a" * 129, False), ("abc_DEF-123456789", True), ("abc.def/123456789", False),
    ("a" * 16 + "\n", False),
])
def test_token_shape(value, ok):
    assert looks_like_token(value) is ok


def test_issue_link_stores_only_hash(db_session, main_episode):
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    token = issue_link(db_session, main_episode.id, now)
    (link,) = db_session.execute(select(PatientLink)).scalars().all()
    assert link.episode_id == main_episode.id
    assert link.token_hash == hash_token(token)
    assert token not in link.token_hash
    expires = link.expires_at if link.expires_at.tzinfo else link.expires_at.replace(tzinfo=UTC)
    assert expires == now + timedelta(days=30)
    assert link.revoked_at is None


def test_issue_link_uses_ttl_setting(db_session, main_episode, monkeypatch):
    monkeypatch.setattr(get_settings(), "patient_link_ttl_days", 7)
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    issue_link(db_session, main_episode.id, now)
    link = db_session.execute(select(PatientLink)).scalar_one()
    expires = link.expires_at if link.expires_at.tzinfo else link.expires_at.replace(tzinfo=UTC)
    assert expires == now + timedelta(days=7)


def test_issue_link_refuses_unknown_and_control_episodes(db_session, main_episode):
    main_episode.group = "control"
    db_session.commit()
    for episode_id in (main_episode.id, "missing"):
        with pytest.raises(LookupError):
            issue_link(db_session, episode_id, datetime.now(UTC))
    assert db_session.execute(select(PatientLink)).scalars().all() == []


def test_issued_link_opens_session(client, db_session, main_episode):
    clinic = db_session.execute(select(Clinic)).scalar_one()
    clinic.patient_settings = json.dumps(SETTINGS, ensure_ascii=False)
    db_session.commit()
    token = issue_link(db_session, main_episode.id, datetime.now(UTC))
    response = client.get("/v1/patient/session", headers={"X-Patient-Link": token})
    assert response.status_code == 200
    assert response.json()["state"] == "active"


def test_issue_link_script_prints_url(db_session, main_episode, monkeypatch, capsys):
    from scripts import issue_link as script

    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(script, "session_scope", scope)
    assert script.main([main_episode.id, "--base-url", "http://127.0.0.1:8763/"]) == 0
    url = capsys.readouterr().out.strip()
    prefix = "http://127.0.0.1:8763/assets/pilot/index.html#/p/"
    assert url.startswith(prefix)
    token = url.removeprefix(prefix)
    link = db_session.execute(select(PatientLink)).scalar_one()
    assert link.token_hash == hash_token(token)
    assert script.main(["missing"]) == 1
    assert "missing" not in capsys.readouterr().out


@pytest.mark.parametrize("days", [0, 91, -1])
def test_link_ttl_bounds(days):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, patient_link_ttl_days=days)


@pytest.mark.parametrize("days", [1, 30, 90])
def test_link_ttl_allowed(days):
    assert Settings(_env_file=None, patient_link_ttl_days=days).patient_link_ttl_days == days


def production_values(**overrides) -> dict:
    values = {
        "environment": "production",
        "mis_hmac_secret": "test-hmac-" + "a" * 32,
        "pilot_salt": "test-pilot-" + "b" * 32,
        "contact_encryption_key": "test-key-" + "c" * 32,
        "contact_hash_salt": "test-hash-" + "d" * 32,
        "patient_link_secret": "test-link-" + "e" * 32,
        "staff_tokens": {},
        "mis_clinic_id": "test-clinic",
    }
    return {**values, **overrides}


def test_production_accepts_link_secret():
    assert Settings(_env_file=None, **production_values()).environment == "production"


@pytest.mark.parametrize("secret", ["dev-patient-link-secret", "short", "dev-" + "x" * 40,
                                    " " * 40])
def test_production_rejects_weak_link_secret(secret):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **production_values(patient_link_secret=secret))
    assert "patient_link_secret" in str(error.value)
    if secret.strip():
        assert secret not in str(error.value)


def test_local_allows_dev_link_secret():
    assert Settings(_env_file=None, environment="local").patient_link_secret.startswith("dev-")


def test_migration_downgrade_restores_theme_keys(empty_engine):
    cfg = alembic_config()
    with empty_engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, B4_REVISION)
        conn.execute(text(
            "INSERT INTO clinics (id, name, theme, service_enabled, created_at, updated_at) "
            "VALUES ('c1', 'Демо', :theme, :on, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"on": True, "theme": '{"logo": "https://example-clinic.ru/l.svg", "title": "К"}'})
        command.upgrade(cfg, "head")
        command.downgrade(cfg, B4_REVISION)
        inspector = inspect(conn)
        assert "patient_links" not in inspector.get_table_names()
        assert "goal_doctors" not in inspector.get_table_names()
        assert "chosen_goal_id" not in {c["name"] for c in inspector.get_columns("episodes")}
        assert json.loads(conn.execute(text("SELECT theme FROM clinics")).scalar_one()) == {
            "logo": "https://example-clinic.ru/l.svg", "title": "К"}
        command.upgrade(cfg, "head")
        assert_b6_schema(conn)
