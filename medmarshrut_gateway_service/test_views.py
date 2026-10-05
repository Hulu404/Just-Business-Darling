"""Security boundaries of path-service projections."""
from __future__ import annotations

import json
import unittest

from views import patient_episode, staff_episode


RAW = {
    "id": "episode-1", "status": "manual_review", "manual_reason": "rule_not_approved",
    "created_at": "2026-01-01T10:00:00Z", "updated_at": "2026-01-01T10:00:00Z",
    "source_report": {"patient_ref": "demo-patient-1", "study_type": "ct", "finding_code": "DEMO_CT_NODULE",
                      "conclusion": "Текст врача", "confidence": 0.91, "source_model": "demo-model",
                      "physician_id": "doctor-1", "source_report_id": "job-1"},
    "plan_steps": [{"id": "step-1", "kind": "manual_review", "description":
                    "Review source report: rule_not_approved", "status": "open", "cycle": 1,
                    "decision_source": "source_report"}],
    "audit_events": [{"event_type": "episode_created", "actor": "system", "details": {"confidence": 0.91}}],
}


class ProjectionTests(unittest.TestCase):
    def test_patient_has_only_allowlisted_fields(self):
        result = patient_episode(RAW)
        encoded = json.dumps(result)
        for secret in ("confidence", "model", "audit", "physician_id", "source_report_id", "rule_not_approved"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(result["steps"][0]["description"], "Врач уточняет план")
        self.assertEqual(result["conclusion"], "Текст врача")

    def test_active_with_old_reason_is_not_manual_review(self):
        active = {**RAW, "status": "active"}
        result = staff_episode(active, "Демо-пациент")
        self.assertEqual(result["reason"], "")
        self.assertEqual(result["status"], "active")

    def test_unknown_status_and_reason_are_preserved(self):
        unknown = {**RAW, "status": "later", "manual_reason": "new_reason"}
        with self.assertLogs("views", "WARNING"):
            result = staff_episode(unknown, "Демо-пациент")
        self.assertEqual(result["status"], "later")


if __name__ == "__main__":
    unittest.main()
