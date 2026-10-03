import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from auth import signature, verify
from candidates import review_candidates
from rules import Ruleset
from service import make_handler
from store import ConflictError, EpisodeStore, PathError

SECRET = "test-shared-secret-long"
ADMIN = "test-admin-token-long"


def report(**updates):
    value = {"source_service": "medmarshrut_image_service", "source_report_id": "job-1",
        "source_report_version": 1, "study_type": "mr", "study_uid": "1.2.3.4", "patient_ref": "patient-1",
        "anatomy": "BRAIN", "protocol_name": "MR_BRAIN", "finding_code": "SYNTHETIC",
        "conclusion": "Reviewed synthetic conclusion", "confidence": 0.01,
        "source_model": "fixture-model", "physician_id": "doctor-1",
        "confirmed_at": "2026-10-03T12:00:00+00:00", "confirmation_status": "confirmed"}
    value.update(updates)
    return value


class PathServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps({"version": "clinic-test-v1",
            "supported_protocols": [{"study_type": "mr", "anatomy": "BRAIN", "protocol_name": "MR_BRAIN"}],
            "rules": [{"study_type": "mr", "anatomy": "BRAIN", "protocol_name": "MR_BRAIN",
                "finding_code": "SYNTHETIC", "approved": True,
                "steps": [{"kind": "appointment", "description": "Review synthetic case"}]}]}), encoding="utf-8")
        self.db_path = self.root / "state.sqlite3"
        self.store = EpisodeStore(self.db_path, Ruleset(self.rules_path))
        self.addCleanup(lambda: self.store.close())

    def test_mr_idempotence_conflict_and_restart(self):
        episode, duplicate = self.store.ingest(report())
        self.assertFalse(duplicate)
        self.assertEqual(episode.status, "active")
        self.assertEqual(episode.source_report.study_type, "mr")
        self.assertEqual(episode.rule_version, "clinic-test-v1")
        same, duplicate = self.store.ingest(report())
        self.assertTrue(duplicate)
        self.assertEqual(same.id, episode.id)
        self.assertEqual(len(same.audit_events), 1)
        with self.assertRaises(ConflictError):
            self.store.ingest(report(conclusion="Changed same version"))
        revised, duplicate = self.store.ingest(report(source_report_version=2, conclusion="Revised synthetic conclusion"))
        self.assertFalse(duplicate)
        self.assertNotEqual(revised.id, episode.id)
        self.assertEqual(revised.manual_reason, "report_revision")
        self.store.close()
        self.store = EpisodeStore(self.db_path, Ruleset(self.rules_path))
        restored = self.store.get(episode.id)
        self.assertEqual(restored.source_report.physician_id, "doctor-1")
        self.assertEqual(restored.plan_steps[0].description, "Review synthetic case")
        with self.assertRaises(ConflictError):
            self.store.close_episode(episode.id, "doctor-1", "done")
        for action in ("offer", "confirm", "attend"):
            self.store.transition(episode.id, restored.plan_steps[0].id, action, "coordinator",
                evidence="fixture evidence", appointment_at="2026-10-04T10:00:00+00:00" if action == "offer" else None)
        done, _ = self.store.confirmed_outcome(episode.id, restored.plan_steps[0].id,
            {"source": "staff_form", "event_id": "fixture-visit", "physician_id": "doctor-1",
             "confirmed_at": "2026-10-04T11:00:00+00:00", "summary": "synthetic completed", "next_steps": []})
        self.assertEqual(done.plan_steps[0].status, "completed")
        closed = self.store.close_episode(episode.id, "doctor-1", "synthetic completed")
        self.assertEqual(closed.status, "completed")
        self.assertEqual(len(closed.audit_events), 6)

    def test_unconfirmed_unknown_and_protocol_are_manual(self):
        with self.assertRaisesRegex(PathError, "physician-confirmed"):
            self.store.ingest(report(confirmation_status="draft"))
        unknown, _ = self.store.ingest(report(source_report_id="job-2", finding_code="UNKNOWN"))
        self.assertEqual(unknown.status, "manual_review")
        self.assertEqual(unknown.manual_reason, "unknown_finding_code")
        unsupported, _ = self.store.ingest(report(source_report_id="job-3", protocol_name="OTHER"))
        self.assertEqual(unsupported.manual_reason, "unsupported_protocol")
        missing_protocol, _ = self.store.ingest(report(source_report_id="job-5", protocol_name=""))
        self.assertEqual(missing_protocol.manual_reason, "unsupported_protocol")
        missing, _ = self.store.ingest(report(source_report_id="job-4", patient_ref=None))
        self.assertEqual(missing.manual_reason, "missing_patient_ref")
        reviewed = self.store.add_manual_plan(unknown.id, "doctor-2", [{"kind": "follow_up", "description": "Manual follow-up"}])
        self.assertEqual(reviewed.status, "active")
        self.assertEqual(reviewed.plan_steps[0].status, "completed")
        self.assertEqual(reviewed.plan_steps[1].status, "open")

    def test_confidence_does_not_select_plan_and_candidates_are_not_plan_steps(self):
        high, _ = self.store.ingest(report(source_report_id="high", confidence=0.99))
        low, _ = self.store.ingest(report(source_report_id="low", confidence=0.01))
        self.assertEqual([s.description for s in high.plan_steps], [s.description for s in low.plan_steps])
        class Proposer:
            def propose(self, source_report):
                return [{"text": "possible follow-up", "rationale": "synthetic"}]
        candidates = review_candidates(Proposer(), high.source_report)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(self.store.get(high.id).plan_steps), 1)

    def test_unapproved_rule_stays_manual(self):
        config = json.loads(self.rules_path.read_text(encoding="utf-8"))
        config["version"] = "clinic-test-v2"
        config["rules"][0]["approved"] = False
        self.rules_path.write_text(json.dumps(config), encoding="utf-8")
        other = EpisodeStore(self.root / "unapproved.sqlite3", Ruleset(self.rules_path))
        try:
            episode, _ = other.ingest(report())
            self.assertEqual(episode.status, "manual_review")
            self.assertEqual(episode.manual_reason, "rule_not_approved")
        finally:
            other.close()

    def test_default_rules_never_auto_route(self):
        default = Path(__file__).with_name("rules.json")
        other = EpisodeStore(self.root / "default.sqlite3", Ruleset(default))
        try:
            episode, _ = other.ingest(report())
            self.assertEqual(episode.status, "manual_review")
            self.assertEqual(episode.manual_reason, "unsupported_protocol")
        finally:
            other.close()

    def test_http_signature_replay_and_read_auth(self):
        self.assertFalse(verify(SECRET, "1000000000", signature(SECRET, "1000000000", b"{}"), b"{}",
                                current_time=1000000400))
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, SECRET, ADMIN))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        body = json.dumps(report()).encode()
        timestamp = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-Path-Timestamp": timestamp,
                   "X-Path-Signature": signature(SECRET, timestamp, body)}
        with urlopen(Request(url + "/v1/reports", data=body, headers=headers, method="POST")) as response:
            self.assertEqual(response.status, 201)
            episode_id = json.load(response)["episode_id"]
        with urlopen(Request(url + "/v1/reports", data=body, headers=headers, method="POST")) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(json.load(response)["duplicate"])
        second = json.dumps(report(source_report_id="job-alias")).encode()
        alias_headers = {**headers, "X-Path-Signature": signature(SECRET, timestamp, second)}
        with urlopen(Request(url + "/v1/episodes", data=second, headers=alias_headers, method="POST")) as response:
            self.assertEqual(response.status, 201)
        with self.assertRaises(HTTPError) as failure:
            urlopen(Request(url + "/v1/reports", data=body, headers={**headers, "X-Path-Signature": "sha256=" + "0" * 64}, method="POST"))
        self.assertEqual(failure.exception.code, 403)
        draft = json.dumps(report(source_report_id="draft", confirmation_status="draft")).encode()
        draft_headers = {**headers, "X-Path-Signature": signature(SECRET, timestamp, draft)}
        with self.assertRaises(HTTPError) as failure:
            urlopen(Request(url + "/v1/reports", data=draft, headers=draft_headers, method="POST"))
        self.assertEqual(failure.exception.code, 400)
        with self.assertRaises(HTTPError) as failure:
            urlopen(url + "/v1/episodes/" + episode_id)
        self.assertEqual(failure.exception.code, 403)
        with urlopen(Request(url + "/v1/episodes/" + episode_id, headers={"Authorization": "Bearer " + ADMIN})) as response:
            episode = json.load(response)
            self.assertEqual(episode["source_report"]["physician_id"], "doctor-1")
        step_id = episode["plan_steps"][0]["id"]
        admin_headers = {"Authorization": "Bearer " + ADMIN, "Content-Type": "application/json"}
        for action in ("offer", "confirm", "attend"):
            payload = {"actor": "coordinator", "evidence": "fixture completed"}
            if action == "offer":
                payload["appointment_at"] = "2026-10-04T10:00:00+00:00"
            with urlopen(Request(url + f"/v1/episodes/{episode_id}/steps/{step_id}/{action}",
                    data=json.dumps(payload).encode(), headers=admin_headers, method="POST")) as response:
                self.assertEqual(response.status, 200)
        outcome = {"source": "staff_form", "event_id": "http-fixture-visit", "physician_id": "doctor-1",
            "confirmed_at": "2026-10-04T11:00:00+00:00", "summary": "synthetic completed", "next_steps": []}
        with urlopen(Request(url + f"/v1/episodes/{episode_id}/outcomes",
                data=json.dumps({"step_id": step_id, "outcome": outcome}).encode(),
                headers=admin_headers, method="POST")) as response:
            self.assertEqual(json.load(response)["episode"]["plan_steps"][0]["status"], "completed")
        with urlopen(Request(url + f"/v1/episodes/{episode_id}/close",
                data=json.dumps({"actor": "doctor-1", "outcome": "fixture outcome"}).encode(),
                headers=admin_headers, method="POST")) as response:
            self.assertEqual(json.load(response)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
