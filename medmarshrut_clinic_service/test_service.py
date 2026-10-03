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

    def test_hmac_helper(self):
        
        self.assertTrue(verify(SECRET, "1000000000", signature(SECRET, "1000000000", b"{}"), b"{}",
                               current_time=1000000200))
       
        self.assertFalse(verify(SECRET, "1000000000", signature(SECRET, "1000000000", b"{}"), b"{}",
                                current_time=1000000000 + 1000))


if __name__ == "__main__":
    unittest.main()