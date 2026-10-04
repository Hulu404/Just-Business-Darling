"""Task 06: clinic routes of the gateway — signatures, tokens by session clinic, partner visibility, referral links."""
from __future__ import annotations

import json

from store import StoreError
from test_gateway import PATH_AUTH, GatewayTestCase


class LinkStore:
    def __init__(self):
        self.links: dict[str, dict] = {}
        self.fail_next = False

    def link_referral(self, referral_id, episode_id, step_id, created_by):
        if self.fail_next:
            self.fail_next = False
            raise StoreError("db down")
        self.links.setdefault(referral_id, {"referral_id": referral_id, "episode_id": episode_id, "step_id": step_id,
                                            "created_by": created_by, "created_at": "2026-10-04T10:00:00+00:00"})
        return self.links[referral_id]

    def referral_links(self, ids=None):
        return {k: {"episode_id": v["episode_id"], "step_id": v["step_id"]} for k, v in self.links.items()
                if ids is None or k in ids}

    def pending_patient_messages(self, *_):
        return []

    def explanation(self, *_):
        return None


EPISODE = {"id": "ep-1", "status": "active", "manual_reason": None, "created_at": "2026-10-04T10:00:00Z",
           "updated_at": "2026-10-04T10:00:00Z", "rule_version": "r1",
           "source_report": {"patient_ref": "demo-patient-3", "study_type": "ct", "anatomy": "CHEST",
                             "protocol_name": "CHEST_STANDARD", "finding_code": "DEMO_CT_NODULE",
                             "conclusion": "Заключение врача", "source_report_id": "job-1"},
           "plan_steps": [{"id": "s1", "kind": "test", "status": "open", "position": 1,
                           "description": "Контрольная КТ органов грудной клетки"}], "audit_events": []}
PARTNER_CARD = {"visibility": "partner", "referral": {"id": "ref-1", "status": "proposed"},
                "patient": {"id": "p-3", "patient_ref": "demo-patient-3", "home_clinic_id": "clinic-central",
                            "home_clinic_name": "Центральная", "status": "active"},
                "anamnesis": [{"id": "a1", "kind": "diagnosis", "text": "ХОБЛ", "shareable": True}]}


class ClinicGatewayTests(GatewayTestCase):
    def setUp(self):
        super().setUp()
        self.store = LinkStore()
        self.gateway.store = self.store
        self.referrals: list[dict] = []
        self.token = {clinic: token for token, clinic in self.staff_tokens.items()}
        self.path.routes.update({("GET", "/v1/episodes/ep-1"): (200, EPISODE),
                                 ("POST", "/v1/episodes/ep-1/steps/s1/offer"): (200, EPISODE),
                                 ("POST", "/v1/episodes/ep-1/steps/s1/confirm"): (200, EPISODE)})
        self.clinic.routes.update({
            ("GET", "/v1/referrals"): lambda r: (200, {"referrals": list(self.referrals)}),
            ("GET", "/v1/clinics"): (200, {"clinics": [{"id": "clinic-central", "name": "Центральная"},
                                                       {"id": "clinic-partner-1", "name": "Лесная"}]}),
            ("GET", "/v1/patients?limit=500"): (200, {"patients": [{"id": "p-3", "patient_ref": "demo-patient-3",
                                                                    "full_name": "Олег Романов"}]}),
            ("POST", "/v1/patients/p-3/anamnesis"): lambda r: (201, {"entry": json.loads(r["body"])}),
            ("GET", "/v1/patients/p-3/card"): (200, PARTNER_CARD),
            ("POST", "/v1/route-candidates"): self.signed(lambda body: (200, {
                "patient_ref": body["patient_ref"], "home_clinic_id": "clinic-central", "reason": None,
                "candidates": [{"clinic_id": "clinic-central", "role": "home", "referral_required": False},
                               {"clinic_id": "clinic-partner-1", "role": "partner", "referral_required": True}]})),
            ("POST", "/v1/referrals"): self.signed(self.create_referral),
            ("POST", "/v1/referrals/ref-1/complete"): (200, {"id": "ref-1", "status": "completed"}),
            ("POST", "/v1/referrals/ref-1/accept"): (200, {"id": "ref-1", "status": "accepted"}),
        })

    def signed(self, answer):
        def handler(request):
            headers = request["headers"]
            if not PATH_AUTH.verify(self.secrets["CLINIC_SHARED_SECRET"], headers.get("X-Path-Timestamp", ""),
                                    headers.get("X-Path-Signature", ""), request["body"]):
                return 403, {"error": "Authorization required"}
            return answer(json.loads(request["body"]))
        return handler

    def create_referral(self, body):
        referral = {"id": f"ref-{len(self.referrals) + 1}", "status": "proposed", "patient_id": "p-3", **body}
        self.referrals.append(referral)
        return 201, referral

    def clinic_auth(self, fragment):
        return [r["headers"].get("Authorization") for r in self.clinic.requests if fragment in r["path"]]

    def test_candidates_and_referral_are_signed_and_take_identity_from_session(self):
        self.login("staff")
        status, _, body = self.call("GET", "/api/staff/episodes/ep-1/route-candidates", role="staff")
        self.assertEqual(status, 200, body)
        self.assertEqual([c["clinic_id"] for c in body["candidates"]], ["clinic-central", "clinic-partner-1"])
        sent = json.loads(next(r for r in self.clinic.requests if r["path"] == "/v1/route-candidates")["body"])
        self.assertEqual(sent["scope"], {"study_type": "ct", "anatomy": "CHEST", "protocol_name": "CHEST_STANDARD",
                                         "finding_code": "DEMO_CT_NODULE"})
        status, _, body = self.call("POST", "/api/staff/episodes/ep-1/steps/s1/referral", role="staff", body={
            "to_clinic_id": "clinic-partner-1", "reason": "Контрольная КТ", "from_clinic_id": "clinic-partner-2",
            "created_by": "attacker"})
        self.assertEqual(status, 201, body)
        self.assertEqual((self.referrals[0]["from_clinic_id"], self.referrals[0]["created_by"]),
                         ("clinic-central", "coordinator-natalia"))
        self.assertEqual(self.store.links["ref-1"]["step_id"], "s1")

    def test_repeat_after_failed_link_does_not_create_a_second_referral(self):
        self.login("staff")
        self.store.fail_next = True
        payload = {"to_clinic_id": "clinic-partner-1", "reason": "Контрольная КТ"}
        status, _, body = self.call("POST", "/api/staff/episodes/ep-1/steps/s1/referral", role="staff", body=payload)
        self.assertEqual((status, body["error"]["code"]), (503, "link_not_saved"))
        status, _, body = self.call("POST", "/api/staff/episodes/ep-1/steps/s1/referral", role="staff", body=payload)
        self.assertEqual(status, 200, body)
        self.assertEqual(len(self.referrals), 1)
        self.assertEqual(body["referral"]["id"], "ref-1")
        self.assertEqual(self.store.links["ref-1"]["episode_id"], "ep-1")

    def test_tokens_follow_the_session_clinic(self):
        self.login("staff")
        status, _, body = self.call("POST", "/api/staff/patients/demo-patient-3/anamnesis", role="staff", body={
            "kind": "note", "text": "Звонить после 18:00", "shareable": False, "clinic_id": "clinic-partner-1",
            "author_id": "attacker", "author_role": "physician"})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["entry"]["clinic_id"], "clinic-central")
        self.assertEqual((body["entry"]["author_id"], body["entry"]["author_role"]), ("coordinator-natalia", "coordinator"))
        self.assertEqual(set(self.clinic_auth("/anamnesis")), {"Bearer " + self.token["clinic-central"]})
        self.login("partner", clinic_id="clinic-partner-1")
        self.assertEqual(self.call("GET", "/api/partner/patients/p-3/card", role="partner")[0], 200)
        self.assertEqual(self.clinic_auth("/v1/patients/p-3/card")[-1], "Bearer " + self.token["clinic-partner-1"])

    def test_roles_cannot_cross(self):
        self.login("partner", clinic_id="clinic-partner-1")
        for method, route in (("GET", "/api/staff/referrals"), ("GET", "/api/staff/patients/demo-patient-3/card"),
                              ("POST", "/api/staff/episodes/ep-1/steps/s1/referral")):
            self.assertEqual(self.call(method, route, role="partner", body={} if method == "POST" else None)[0], 403)
        self.login("staff")
        for method, route in (("GET", "/api/partner/queue"), ("POST", "/api/partner/referrals/ref-1/accept")):
            self.assertEqual(self.call(method, route, role="staff", body={} if method == "POST" else None)[0], 403)

    def test_partner_gets_exactly_the_service_card(self):
        self.login("partner", clinic_id="clinic-partner-1")
        status, _, body = self.call("GET", "/api/partner/patients/p-3/card", role="partner")
        self.assertEqual((status, body), (200, PARTNER_CARD))
        for word in ("full_name", "birth_date", "contact", "Олег", "Заключение врача"):
            self.assertNotIn(word, json.dumps(body, ensure_ascii=False))

    def test_partner_complete_does_not_touch_the_path_service(self):
        self.login("partner", clinic_id="clinic-partner-1")
        before = len(self.path.requests)
        status, _, body = self.call("POST", "/api/partner/referrals/ref-1/complete", role="partner", body={"actor": "x"})
        self.assertEqual((status, body["referral"]["status"]), (200, "completed"))
        self.assertEqual(len(self.path.requests), before)
        sent = json.loads(next(r for r in self.clinic.requests if r["path"].endswith("/complete"))["body"])
        self.assertEqual(sent, {"actor": "partner1-coordinator"})

    def test_partner_booking_needs_accepted_referral_and_marks_evidence(self):
        self.login("staff")
        route = "/api/staff/episodes/ep-1/steps/s1/confirm"
        payload = {"partner_time": "2026-12-01T10:00:00+03:00", "partner_clinic_id": "clinic-partner-1"}
        self.assertEqual(self.call("POST", route, role="staff", body=payload)[0], 409)
        self.referrals.append({"id": "ref-1", "patient_ref": "demo-patient-3", "from_clinic_id": "clinic-central",
                               "to_clinic_id": "clinic-partner-1", "status": "accepted"})
        status, _, body = self.call("POST", route, role="staff", body=payload)
        self.assertEqual(status, 200, body)
        sent = [json.loads(r["body"]) for r in self.path.requests if r["method"] == "POST"]
        self.assertEqual([s["appointment_at"] for s in sent], ["2026-12-01T10:00:00+03:00"] * 2)
        self.assertTrue(all("у партнёра" in s["evidence"].lower() for s in sent))

    def test_patients_limit_is_checked_before_the_service(self):
        self.login("staff")
        for limit in ("0", "501", "abc", "-1"):
            self.assertEqual(self.call("GET", f"/api/staff/patients?limit={limit}", role="staff")[0], 400, limit)
        self.assertFalse(any(r["path"].startswith("/v1/patients?limit=0") for r in self.clinic.requests))

    def test_patient_documents_list_only_own_referrals(self):
        self.referrals += [{"id": "ref-1", "patient_ref": "demo-patient-1", "to_clinic_id": "clinic-partner-1",
                            "reason": "КТ", "status": "proposed", "created_at": "2026-10-04T10:00:00Z"},
                           {"id": "ref-2", "patient_ref": "other", "to_clinic_id": "clinic-partner-1",
                            "reason": "Чужое", "status": "accepted", "created_at": "2026-10-04T10:00:00Z"}]
        self.login("patient")
        status, _, body = self.call("GET", "/api/patient/documents", role="patient")
        self.assertEqual(status, 200, body)
        self.assertEqual([(r["id"], r["to_clinic_name"]) for r in body["referrals"]], [("ref-1", "Лесная")])
