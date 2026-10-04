import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from auth import signature, verify
from catalog import Catalog
from store import ConflictError, MedError, MedStore

SECRET = "test-shared-secret-long"


def make_catalog(root: Path) -> tuple[Path, Path]:
    cat = root / "catalog.json"
    cat.write_text(json.dumps({
        "version": "test-cat-1",
        "pharmacies": [
            {"id": "p1", "name": "P1", "network": "n", "city": "M", "active": True,
             "order_url_template": "https://p1.demo/order/{order_id}"},
            {"id": "p2", "name": "P2", "network": "n", "city": "M", "active": True,
             "order_url_template": "https://p2.demo/order/{order_id}"},
        ],
        "medications": [
            {"id": "amoxil", "inn": "amoxicillin", "trade_name": "Amoxil", "form": "capsule",
             "strength": "500 mg", "atc_code": "J01CA04", "prescription_required": True, "active": True},
            {"id": "hiconcil", "inn": "amoxicillin", "trade_name": "Hiconcil", "form": "capsule",
             "strength": "500 mg", "atc_code": "J01CA04", "prescription_required": True, "active": True},
            {"id": "panadol", "inn": "paracetamol", "trade_name": "Panadol", "form": "tablet",
             "strength": "500 mg", "atc_code": "N02BE01", "prescription_required": False, "active": True},
        ],
    }), encoding="utf-8")
    inv = root / "inventory.json"
    inv.write_text(json.dumps({
        "version": "inv-1",
        "inventory": [
            {"pharmacy_id": "p1", "medication_id": "amoxil", "stock": 20, "price": 380.0, "currency": "RUB", "updated_at": "2026-10-04T09:00:00+00:00"},
            {"pharmacy_id": "p2", "medication_id": "amoxil", "stock": 5, "price": 400.0, "currency": "RUB", "updated_at": "2026-10-04T09:00:00+00:00"},
            {"pharmacy_id": "p1", "medication_id": "hiconcil", "stock": 10, "price": 350.0, "currency": "RUB", "updated_at": "2026-10-04T09:00:00+00:00"},
        ],
    }), encoding="utf-8")
    return cat, inv


def prescription(**updates):
    value = {
        "source_service": "medmarshrut_path_service",
        "source_prescription_id": "rx-1",
        "source_prescription_version": 1,
        "patient_ref": "patient-1",
        "physician_id": "doctor-1",
        "confirmed_at": "2026-10-04T09:00:00+00:00",
        "expires_at": "2026-11-04T09:00:00+00:00",
        "conclusion": "Test conclusion",
        "study_uid": "1.2.3.4",
        "items": [
            {"inn": "amoxicillin", "trade_name": "Amoxil", "form": "capsule", "strength": "500 mg",
             "dosage": "1 tid", "duration_days": 7, "quantity": 21, "substitution_allowed": True},
        ],
    }
    value.update(updates)
    return value


class MedicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        cat, inv = make_catalog(self.root)
        self.store = MedStore(self.root / "db.sqlite3", Catalog(cat), inv)
        self.addCleanup(self.store.close)

    def test_ingest_and_idempotence(self):
        p, dup = self.store.ingest_prescription(prescription())
        self.assertFalse(dup)
        self.assertEqual(p.patient_ref, "patient-1")
        same, dup = self.store.ingest_prescription(prescription())
        self.assertTrue(dup)
        self.assertEqual(same.id, p.id)
        with self.assertRaises(ConflictError):
            self.store.ingest_prescription(prescription(conclusion="Changed"))

    def test_reject_unconfirmed_source_and_bad_item(self):
        with self.assertRaises(MedError):
            self.store.ingest_prescription(prescription(source_service="attacker"))
        with self.assertRaises(MedError):
            self.store.ingest_prescription(prescription(items=[]))
        with self.assertRaises(MedError):
            self.store.ingest_prescription(prescription(items=[{"inn": "amoxicillin"}]))

    def test_offers_include_analogs_when_allowed(self):
        p, _ = self.store.ingest_prescription(prescription())
        offers = self.store.match_offers(p.id)
        options = offers["offers"][0]["options"]
        trade_names = {o["trade_name"] for o in options}
        self.assertIn("Amoxil", trade_names)
        self.assertIn("Hiconcil", trade_names)

    def test_offers_exclude_analogs_when_substitution_not_allowed(self):
        p, _ = self.store.ingest_prescription(prescription(items=[
            {"inn": "amoxicillin", "trade_name": "Amoxil", "form": "capsule", "strength": "500 mg",
             "dosage": "1 tid", "duration_days": 7, "quantity": 21, "substitution_allowed": False},
        ]))
        offers = self.store.match_offers(p.id)
        options = offers["offers"][0]["options"]
        trade_names = {o["trade_name"] for o in options}
        self.assertEqual(trade_names, {"Amoxil"})

    def test_place_order_and_quantity_limit(self):
        p, _ = self.store.ingest_prescription(prescription())
        order = self.store.place_order(p.id, "patient-1", "p1", [{"medication_id": "amoxil", "quantity": 10}])
        self.assertEqual(order.status, "placed")
        self.assertEqual(order.total, 3800.0)
        self.assertIsNotNone(order.redirect_url)
        self.assertEqual(order.redirect_url, f"https://p1.demo/order/{order.id}")
        with self.assertRaises(ConflictError):
            self.store.place_order(p.id, "patient-1", "p1", [{"medication_id": "amoxil", "quantity": 15}])

    def test_redirect_url_cleared_after_pickup(self):
        p, _ = self.store.ingest_prescription(prescription())
        order = self.store.place_order(p.id, "patient-1", "p1", [{"medication_id": "amoxil", "quantity": 5}])
        self.assertIsNotNone(order.redirect_url)
        self.store.transition_order(order.id, "confirm", "pharmacist", None)
        self.store.transition_order(order.id, "ready", "pharmacist", None)
        done = self.store.transition_order(order.id, "picked_up", "patient-1", None)
        self.assertEqual(done.status, "picked_up")
        self.assertIsNone(done.redirect_url)

    def test_order_lifecycle_and_patient_isolation(self):
        p, _ = self.store.ingest_prescription(prescription())
        order = self.store.place_order(p.id, "patient-1", "p1", [{"medication_id": "amoxil", "quantity": 5}])
        self.store.transition_order(order.id, "confirm", "pharmacist", None)
        self.store.transition_order(order.id, "ready", "pharmacist", None)
        done = self.store.transition_order(order.id, "picked_up", "patient-1", None)
        self.assertEqual(done.status, "picked_up")
        with self.assertRaises(ConflictError):
            self.store.transition_order(order.id, "cancel", "patient-1", None)
        with self.assertRaises(ConflictError):
            self.store.place_order(p.id, "other-patient", "p1", [{"medication_id": "amoxil", "quantity": 1}])

    def test_substitution_not_allowed_blocks_order(self):
        p, _ = self.store.ingest_prescription(prescription(items=[
            {"inn": "amoxicillin", "trade_name": "Amoxil", "form": "capsule", "strength": "500 mg",
             "dosage": "1 tid", "duration_days": 7, "quantity": 21, "substitution_allowed": False},
        ]))
        with self.assertRaises(ConflictError):
            self.store.place_order(p.id, "patient-1", "p1", [{"medication_id": "hiconcil", "quantity": 5}])

    def test_expired_prescription(self):
        p, _ = self.store.ingest_prescription(prescription(
            confirmed_at="2020-01-01T00:00:00+00:00", expires_at="2020-02-01T00:00:00+00:00"))
        with self.assertRaises(ConflictError):
            self.store.place_order(p.id, "patient-1", "p1", [{"medication_id": "amoxil", "quantity": 1}])

    def test_hmac_helper(self):
        self.assertTrue(verify(SECRET, "1000000000", signature(SECRET, "1000000000", b"{}"), b"{}",
                               current_time=1000000200))
        self.assertFalse(verify(SECRET, "1000000000", signature(SECRET, "1000000000", b"{}"), b"{}",
                                current_time=1000000000 + 1000))


if __name__ == "__main__":
    unittest.main()