"""New path routes: ownership, access and actor identity."""
from __future__ import annotations

import json
from copy import deepcopy

from test_gateway import GatewayTestCase


def episode(eid: str, ref: str) -> dict:
    return {"id": eid, "status": "active", "manual_reason": None, "created_at": "2026-01-01T10:00:00Z",
            "updated_at": "2026-01-01T10:00:00Z", "rule_version": "demo-rules-1",
            "source_report": {"patient_ref": ref, "study_type": "ct", "finding_code": "DEMO_CT_NODULE",
                              "conclusion": "Заключение врача", "confidence": 0.91, "source_model": "demo-model",
                              "physician_id": "doctor-1", "confirmed_at": "2026-01-01T10:00:00Z"},
            "plan_steps": [{"id": "step-1", "status": "confirmed", "kind": "appointment",
                            "description": "Приём терапевта в течение 24 часов", "cycle": 1,
                            "appointment_at": "2026-01-02T10:00:00Z", "due_at": None,
                            "decision_source": "rule:demo-rules-1"}],
            "audit_events": [{"event_type": "episode_created", "actor": "system", "details": {"confidence": 0.91}}]}


class FakeStore:
    def __init__(self):
        self.appointment_updates = []

    def explanation(self, *_):
        return {"seen": "Врач подтвердил находку", "means": "Обсудите её на приёме"}

    def slots(self, *_):
        return []

    def pending_patient_messages(self, *_):
        return []

    def reserve_slot(self, *_):
        return {"id": 5, "starts_at": "2026-12-01T10:00:00+03:00", "place": "Демо", "format": "Очно", "reused": False}, None

    def appointment_status(self, appointment_id, status):
        self.appointment_updates.append((appointment_id, status))

    def undo_reservation(self, *_):
        self.appointment_updates.append(("undone", ""))

    def outcome_timestamp(self, event_id, episode_id, step_id, physician_id, content):
        self.last_outcome = (event_id, episode_id, step_id, physician_id, content)
        return "2026-01-02T12:00:00+00:00"


class PathGatewayTests(GatewayTestCase):
    def setUp(self):
        super().setUp()
        self.own = episode("own-1", "demo-patient-1")
        self.foreign = episode("other-1", "other-patient")
        self.gateway.store = FakeStore()
        self.path.routes.update({
            ("GET", "/v1/episodes"): (200, {"episode_ids": ["own-1", "other-1"]}),
            ("GET", "/v1/episodes/own-1"): (200, self.own),
            ("GET", "/v1/episodes/other-1"): (200, self.foreign),
            ("POST", "/v1/episodes/own-1/steps/step-1/attend"): (200, self.own),
        })
        self.clinic.routes[("GET", "/v1/patients?limit=500")] = (200, {"patients": [
            {"patient_ref": "demo-patient-1", "full_name": "Демо-пациент"},
            {"patient_ref": "other-patient", "full_name": "Другой пациент"}]})

    def test_patient_list_is_filtered_and_redacted(self):
        self.login("patient")
        status, _, body = self.call("GET", "/api/patient/episodes", role="patient")
        self.assertEqual(status, 200, body)
        self.assertEqual([x["id"] for x in body["episodes"]], ["own-1"])
        encoded = json.dumps(body)
        for forbidden in ("confidence", "model", "audit_events", "physician_id", "other-patient"):
            self.assertNotIn(forbidden, encoded)

    def test_patient_get_other_episode_is_404(self):
        self.login("patient")
        self.assertEqual(self.call("GET", "/api/patient/episodes/other-1", role="patient")[0], 404)

    def test_patient_and_doctor_cannot_use_staff_transition(self):
        for role in ("patient", "doctor"):
            self.login(role)
            status, _, _ = self.call("POST", "/api/staff/episodes/own-1/steps/step-1/attend",
                                     role=role, body={"actor": "attacker"})
            self.assertEqual(status, 403)

    def test_staff_transition_uses_session_actor(self):
        self.login("staff")
        status, _, body = self.call("POST", "/api/staff/episodes/own-1/steps/step-1/attend",
                                    role="staff", body={"actor": "attacker"})
        self.assertEqual(status, 200, body)
        sent = json.loads(self.path.requests[-1]["body"])
        self.assertEqual(sent["actor"], "coordinator-natalia")
        self.assertNotIn("attacker", json.dumps(sent))

    def test_patient_booking_offers_then_confirms_from_open(self):
        self.own["plan_steps"][0]["status"] = "open"
        self.path.routes.update({
            ("POST", "/v1/episodes/own-1/steps/step-1/offer"): (200, self.own),
            ("POST", "/v1/episodes/own-1/steps/step-1/confirm"): (200, self.own),
        })
        self.login("patient")
        status, _, body = self.call("POST", "/api/patient/episodes/own-1/steps/step-1/book",
                                    role="patient", body={"slot_id": "5", "actor": "attacker"})
        self.assertEqual(status, 200, body)
        sent = [r for r in self.path.requests if r["method"] == "POST"]
        self.assertEqual([r["path"].rsplit("/", 1)[-1] for r in sent], ["offer", "confirm"])
        for request in sent:
            payload = json.loads(request["body"])
            self.assertEqual(payload["actor"], "demo-patient-1")
            self.assertNotIn("attacker", json.dumps(payload))
        self.assertEqual(self.gateway.store.appointment_updates, [(5, "confirmed")])

    def test_patient_booking_offered_confirms_once(self):
        self.own["plan_steps"][0]["status"] = "offered"
        self.path.routes[("POST", "/v1/episodes/own-1/steps/step-1/confirm")] = (200, self.own)
        self.login("patient")
        status, _, body = self.call("POST", "/api/patient/episodes/own-1/steps/step-1/book",
                                    role="patient", body={"slot_id": "5"})
        self.assertEqual(status, 200, body)
        sent = [r for r in self.path.requests if r["method"] == "POST"]
        self.assertEqual([r["path"].rsplit("/", 1)[-1] for r in sent], ["confirm"])

    def test_only_doctor_can_make_plan_and_session_identity_is_used(self):
        self.own["status"] = "manual_review"
        self.path.routes[("POST", "/v1/episodes/own-1/manual-plan")] = (200, self.own)
        route = "/api/doctor/episodes/own-1/manual-plan"
        payload = {"actor": "attacker", "steps": [{"kind": "appointment", "description": "Приём врача"}]}
        for role in ("patient", "staff"):
            self.login(role)
            self.assertEqual(self.call("POST", route, role=role, body=payload)[0], 403)
        self.login("doctor")
        status, _, body = self.call("POST", route, role="doctor", body=payload)
        self.assertEqual(status, 200, body)
        sent = json.loads(self.path.requests[-1]["body"])
        self.assertEqual(sent["actor"], "doctor-demo")
        self.assertNotIn("attacker", json.dumps(sent))

    def test_outcome_attends_then_submits_and_ignores_physician_id(self):
        self.path.routes[("POST", "/v1/episodes/own-1/outcomes")] = (200, {"episode": self.own, "duplicate": False})
        route = "/api/doctor/episodes/own-1/steps/step-1/outcome"
        payload = {"event_id": "visit-1", "summary": "Контроль проведён", "next_steps": [],
                   "physician_id": "attacker"}
        for role in ("patient", "staff"):
            self.login(role)
            self.assertEqual(self.call("POST", route, role=role, body=payload)[0], 403)
        self.login("doctor")
        status, _, body = self.call("POST", route, role="doctor", body=payload)
        self.assertEqual(status, 200, body)
        requests = [r for r in self.path.requests if r["method"] == "POST"]
        self.assertEqual([r["path"].rsplit("/", 1)[-1] for r in requests], ["attend", "outcomes"])
        outcome = json.loads(requests[-1]["body"])["outcome"]
        self.assertEqual(outcome["physician_id"], "doctor-demo")
        self.assertEqual(outcome["confirmed_at"], "2026-01-02T12:00:00+00:00")
        self.assertNotIn("attacker", json.dumps(outcome))

    def test_rules_dry_run_requires_staff_or_doctor(self):
        self.path.routes[("POST", "/v1/rules/dry-run")] = (200, {"dry_run": True, "steps": [],
                                                                    "manual_reason": "rule_not_approved",
                                                                    "rule_version": "demo-rules-1"})
        route = "/api/staff/rules/dry-run"
        payload = {"study_type": "ct", "anatomy": "CHEST", "protocol_name": "CT_CHEST",
                   "finding_code": "DEMO_CT_NODULE"}
        self.login("patient")
        self.assertEqual(self.call("POST", route, role="patient", body=payload)[0], 403)
        self.login("staff")
        status, _, body = self.call("POST", route, role="staff", body=payload)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["manual_reason"], "rule_not_approved")
