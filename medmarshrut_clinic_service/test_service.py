import json
import tempfile
import unittest
from pathlib import Path

from auth import signature, verify
from network import ClinicNetwork
from store import ClinicError, ClinicStore, ConflictError

SECRET = "test-shared-secret-long"


def make_network(root: Path) -> Path:
    path = root / "network.json"
    path.write_text(json.dumps({
        "version": "test-network-1",
        "clinics": [
            {"id": "clinic-a", "name": "A", "network": "net", "active": True},
            {"id": "clinic-b", "name": "B", "network": "net", "active": True},
            {"id": "clinic-c", "name": "C", "network": "net", "active": True},
        ],
        "capabilities": [
            {"clinic_id": "clinic-a", "study_type": "ct", "anatomy": "CHEST",
             "protocol_name": "CHEST_STANDARD", "finding_code": "*", "approved": True},
            {"clinic_id": "clinic-b", "study_type": "mr", "anatomy": "BRAIN",
             "protocol_name": "MR_BRAIN", "finding_code": "*", "approved": True},
            {"clinic_id": "clinic-c", "study_type": "mr", "anatomy": "BRAIN",
             "protocol_name": "MR_BRAIN", "finding_code": "FINDING_X", "approved": False},
        ],
        "partnerships": [
            {"clinic_a": "clinic-a", "clinic_b": "clinic-b", "direction": "mutual",
             "active": True, "since": "2026-01-01T00:00:00+00:00"}
        ],
    }), encoding="utf-8")
    return path


def patient_payload(**updates):
    value = {"patient_ref": "patient-1", "full_name": "Test Patient",
             "birth_date": "1980-01-01", "sex": "F", "contact": "p@example.invalid"}
    value.update(updates)
    return value


class ClinicServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = ClinicStore(self.root / "clinic.sqlite3", ClinicNetwork(make_network(self.root)))
        self.addCleanup(self.store.close)

    def test_patient_lifecycle_and_anamnesis(self):
        patient = self.store.create_patient("clinic-a", patient_payload())
        self.assertEqual(patient.status, "active")
        with self.assertRaises(ConflictError):
            self.store.create_patient("clinic-a", patient_payload())
        entry = self.store.add_anamnesis(patient.id, "clinic-a", "doc-1", "physician",
                                         {"kind": "diagnosis", "code": "X", "text": "ok",
                                          "shareable": True, "recorded_at": "2026-10-03T12:00:00+00:00"})
        self.assertEqual(entry.version, 1)
        second = self.store.add_anamnesis(patient.id, "clinic-a", "doc-1", "physician",
                                          {"kind": "note", "code": None, "text": "internal",
                                           "shareable": False, "recorded_at": None})
        self.assertEqual(second.version, 2)
        with self.assertRaises(ConflictError):
            self.store.add_anamnesis(patient.id, "clinic-b", "doc-2", "physician",
                                     {"kind": "note", "code": None, "text": "nope",
                                      "shareable": True, "recorded_at": None})
        closed = self.store.set_patient_status(patient.id, "clinic-a", "archived", "doc-1")
        self.assertEqual(closed.status, "archived")
        with self.assertRaises(ConflictError):
            self.store.add_anamnesis(patient.id, "clinic-a", "doc-1", "physician",
                                     {"kind": "note", "code": None, "text": "late",
                                      "shareable": True, "recorded_at": None})
        with self.assertRaises(ConflictError):
            self.store.set_patient_status(patient.id, "clinic-b", "active", "doc-2")

    def test_routing_candidates_and_capability_filter(self):
        patient = self.store.create_patient("clinic-a", patient_payload())
        mr = {"study_type": "mr", "anatomy": "BRAIN", "protocol_name": "MR_BRAIN", "finding_code": "FINDING_X"}
        result = self.store.route_candidates("patient-1", mr)
        self.assertIsNone(result["reason"])
        self.assertEqual({c["clinic_id"] for c in result["candidates"]}, {"clinic-b"})
        ct = {"study_type": "ct", "anatomy": "CHEST", "protocol_name": "CHEST_STANDARD", "finding_code": "ANY"}
        home_only = self.store.route_candidates("patient-1", ct)
        self.assertEqual([c["clinic_id"] for c in home_only["candidates"]], ["clinic-a"])
        unknown = self.store.route_candidates("nobody", mr)
        self.assertEqual(unknown["reason"], "unknown_patient_ref")
        self.assertNotIn("clinic-c", {c["clinic_id"] for c in result["candidates"]})

    def test_referral_lifecycle_and_partner_visibility(self):
        patient = self.store.create_patient("clinic-a", patient_payload())
        self.store.add_anamnesis(patient.id, "clinic-a", "doc-1", "physician",
                                 {"kind": "diagnosis", "code": None, "text": "shared",
                                  "shareable": True, "recorded_at": None})
        self.store.add_anamnesis(patient.id, "clinic-a", "doc-1", "physician",
                                 {"kind": "note", "code": None, "text": "internal",
                                  "shareable": False, "recorded_at": None})
        self.assertIsNone(self.store.patient_card(patient.id, "clinic-b"))
        referral = self.store.create_referral(patient.id, "clinic-a", "clinic-b", "Synthetic", "doc-1")
        before = self.store.patient_card(patient.id, "clinic-b")
        self.assertEqual(before["visibility"], "partner")
        self.assertNotIn("full_name", before["patient"])
        self.assertEqual(len(before["anamnesis"]), 1)
        self.store.referral_action(referral.id, "accept", "clinic-b", "doc-2", "ok")
        after = self.store.patient_card(patient.id, "clinic-b")
        self.assertEqual(after["patient"]["full_name"], "Test Patient")
        # wrong clinic tries to act
        with self.assertRaises(ConflictError):
            self.store.referral_action(referral.id, "accept", "clinic-a", "doc-1", "wrong clinic")
        with self.assertRaises(ConflictError):
            self.store.referral_action(referral.id, "complete", "clinic-a", "doc-1", "wrong clinic")
        # correct clinic completes
        self.store.referral_action(referral.id, "complete", "clinic-b", "doc-2", "done")
        home = self.store.patient_card(patient.id, "clinic-a")
        self.assertEqual(home["visibility"], "home")
        self.assertIn("clinic-b", {x["clinic_id"] for x in home["shared_with"]})
        # cannot cancel after completion
        with self.assertRaises(ConflictError):
            self.store.referral_action(referral.id, "cancel", "clinic-a", "doc-1", "too late")

    def test_referral_requires_active_partner_and_active_patient(self):
        patient = self.store.create_patient("clinic-a", patient_payload())
        with self.assertRaises(ConflictError):
            self.store.create_referral(patient.id, "clinic-a", "clinic-c", "no partnership", "doc-1")
        self.store.set_patient_status(patient.id, "clinic-a", "archived", "doc-1")
        with self.assertRaises(ConflictError):
            self.store.create_referral(patient.id, "clinic-a", "clinic-b", "archived patient", "doc-1")

    def test_xray_capability_is_a_route_candidate(self):
        path = self.root / "xray-network.json"
        path.write_text(json.dumps({"version": "test-xray", "clinics": [{"id": "clinic-a", "name": "A", "network": "net", "active": True}],
            "capabilities": [{"clinic_id": "clinic-a", "study_type": "xray", "anatomy": "CHEST", "protocol_name": "CHEST_PA",
                              "finding_code": "*", "approved": True}], "partnerships": []}), encoding="utf-8")
        store = ClinicStore(self.root / "xray.sqlite3", ClinicNetwork(path))
        self.addCleanup(store.close)
        store.create_patient("clinic-a", patient_payload())
        result = store.route_candidates("patient-1", {"study_type": "xray", "anatomy": "CHEST", "protocol_name": "CHEST_PA",
                                                      "finding_code": "XR_FINDING"})
        self.assertEqual([c["clinic_id"] for c in result["candidates"]], ["clinic-a"])

    def test_hmac_helper(self):
        
        self.assertTrue(verify(SECRET, "1000000000", signature(SECRET, "1000000000", b"{}"), b"{}",
                               current_time=1000000200))
       
        self.assertFalse(verify(SECRET, "1000000000", signature(SECRET, "1000000000", b"{}"), b"{}",
                                current_time=1000000000 + 1000))


class ClinicHttpTests(unittest.TestCase):
    """GET /v1/referrals and the 400 on a bad patients filter, through the real handler."""

    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        from service import make_handler
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = ClinicStore(root / "clinic.sqlite3", ClinicNetwork(make_network(root)))
        self.addCleanup(self.store.close)
        self.tokens = {"token-a-0123456789": "clinic-a", "token-b-0123456789": "clinic-b", "token-c-0123456789": "clinic-c"}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, SECRET, "admin-token-0123456789",
                                                                         self.tokens))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, token):
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        connection.request("GET", path, headers={"Authorization": "Bearer " + token})
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def test_referrals_of_own_clinic_in_both_directions(self):
        patient = self.store.create_patient("clinic-a", patient_payload())
        referral = self.store.create_referral(patient.id, "clinic-a", "clinic-b", "MRI", "coord-a")
        for token in ("token-a-0123456789", "token-b-0123456789"):
            status, body = self.get("/v1/referrals", token)
            self.assertEqual(status, 200, body)
            self.assertEqual([(r["id"], r["patient_ref"]) for r in body["referrals"]], [(referral.id, "patient-1")])
            self.assertNotIn("full_name", json.dumps(body))
        self.assertEqual(self.get("/v1/referrals", "token-c-0123456789"), (200, {"referrals": []}))
        self.assertEqual(self.get("/v1/referrals?status=accepted", "token-a-0123456789"), (200, {"referrals": []}))
        self.assertEqual(self.get("/v1/referrals?status=nope", "token-a-0123456789")[0], 400)

    def test_bad_patients_filter_is_400_not_a_dropped_connection(self):
        for query in ("limit=abc", "limit=0", "limit=501", "status=nope"):
            self.assertEqual(self.get("/v1/patients?" + query, "token-a-0123456789")[0], 400, query)
        self.assertEqual(self.get("/v1/patients?limit=5", "token-a-0123456789")[0], 200)


if __name__ == "__main__":
    unittest.main()