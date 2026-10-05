"""Run a synthetic two-cycle pathway without changing clinic rules or contacting patients."""
from __future__ import annotations

import json
import argparse
import hashlib
import hmac
import os
import tempfile
from pathlib import Path

from rules import Ruleset
from store import EpisodeStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="Persist a new demo database for the browser service")
    args = parser.parse_args()
    if args.db and args.db.exists():
        parser.error(f"Demo database already exists: {args.db}")
    with tempfile.TemporaryDirectory() as directory:
        db_path = args.db if args.db else Path(directory) / "demo.sqlite3"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = EpisodeStore(db_path, Ruleset(Path(__file__).with_name("rules.json")))
        try:
            report = {"source_service": "medmarshrut_image_service", "source_report_id": "synthetic-1",
                "source_report_version": 1, "study_type": "mr", "study_uid": "1.2.3.4.5",
                "patient_ref": "synthetic-patient", "anatomy": "BRAIN", "protocol_name": "MR_BRAIN",
                "finding_code": "SYNTHETIC", "conclusion": "Synthetic confirmed report",
                "confidence": None, "source_model": "none", "physician_id": "demo-doctor",
                "confirmed_at": "2026-10-03T12:00:00+00:00", "confirmation_status": "confirmed"}
            episode, _ = store.ingest(report)
            episode = store.add_manual_plan(episode.id, "demo-doctor",
                [{"kind": "appointment", "description": "First synthetic consultation"}])
            first = episode.plan_steps[-1].id
            for action in ("offer", "confirm", "attend"):
                episode = store.transition(episode.id, first, action, "demo-coordinator", evidence="Synthetic fixture",
                    appointment_at="2026-10-04T10:00:00+00:00" if action == "offer" else None)
            episode, _ = store.confirmed_outcome(episode.id, first,
                {"source": "staff_form", "event_id": "synthetic-visit-1", "physician_id": "demo-doctor",
                 "confirmed_at": "2026-10-04T11:00:00+00:00", "summary": "Synthetic next step approved",
                 "next_steps": [{"kind": "test", "description": "Second synthetic appointment for a test",
                                 "owner": "demo-coordinator", "due_at": "2026-10-10T12:00:00+00:00",
                                 "continue_on": "confirmed_outcome"}]})
            second = episode.plan_steps[-1].id
            episode = store.transition(episode.id, second, "offer", "demo-coordinator",
                evidence="Synthetic second offer", appointment_at="2026-10-08T10:00:00+00:00")
            episode = store.transition(episode.id, second, "confirm", "demo-coordinator", evidence="Synthetic confirmation")
            patient_secret = os.environ.get("PATH_PATIENT_TOKEN", "")
            patient_token = hmac.new(patient_secret.encode(), b"synthetic-patient", hashlib.sha256).hexdigest() if patient_secret else None
            print(json.dumps({"database": str(db_path), "patient_ref": "synthetic-patient",
                "patient_token": patient_token, "patient_page": "http://127.0.0.1:8765/patient",
                "staff_page": "http://127.0.0.1:8765/staff", "episode_id": episode.id,
                "steps": [{"cycle": s.cycle, "description": s.description, "status": s.status,
                           "decision_source": s.decision_source} for s in episode.plan_steps],
                "patient": store.patient_view("synthetic-patient"), "metrics": store.metrics(),
                "outbox": store.outbox()}, ensure_ascii=False, indent=2))
        finally:
            store.close()


if __name__ == "__main__":
    main()
