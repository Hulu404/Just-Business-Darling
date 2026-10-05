"""Synthetic clinic card and routing demo; no patient data is contacted."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from network import ClinicNetwork
from store import ClinicStore


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        db = root / "clinic.sqlite3"
        network = ClinicNetwork(Path(__file__).with_name("network.json"))
        store = ClinicStore(db, network)
        try:
            patient = store.create_patient("clinic-central", {
                "patient_ref": "synthetic-patient-1",
                "full_name": "Synthetic Patient",
                "birth_date": "1980-05-01",
                "sex": "F",
                "contact": "synthetic@example.invalid",
            })
            for kind, text, shareable in (
                ("diagnosis", "Synthetic finding on prior exam", True),
                ("allergy", "Synthetic allergy", True),
                ("note", "Internal clinic note", False),
            ):
                store.add_anamnesis(patient.id, "clinic-central", "demo-doctor", "physician",
                                    {"kind": kind, "code": None, "text": text, "shareable": shareable,
                                     "recorded_at": "2026-10-03T12:00:00+00:00"})
            routing = store.route_candidates("synthetic-patient-1", {
                "study_type": "mr", "anatomy": "BRAIN", "protocol_name": "MR_BRAIN",
                "finding_code": "FINDING_X"})
            referral = store.create_referral(patient.id, "clinic-central", "clinic-partner-1",
                                             "Synthetic referral for MR follow-up", "demo-doctor")
            before = store.patient_card(patient.id, "clinic-partner-1")
            store.referral_action(referral.id, "accept", "clinic-partner-1", "partner-doctor",
                                  "Accepted for synthetic reason")
            after = store.patient_card(patient.id, "clinic-partner-1")
            print(json.dumps({
                "patient": patient.__dict__,
                "routing": routing,
                "referral_created": referral.to_dict(),
                "partner_view_before_accept": before,
                "partner_view_after_accept": after,
                "home_view": store.patient_card(patient.id, "clinic-central"),
                "metrics": store.metrics("clinic-central"),
                "queue_partner": store.queue("clinic-partner-1"),
            }, ensure_ascii=False, indent=2, default=str))
        finally:
            store.close()


if __name__ == "__main__":
    main()