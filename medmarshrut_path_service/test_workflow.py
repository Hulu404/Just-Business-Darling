import json
import tempfile
import unittest
from pathlib import Path

from rules import Ruleset
from store import ConflictError, EpisodeStore
from test_service import report


def next_step(description, due_at="2026-10-10T12:00:00+00:00"):
    return {"kind": "appointment", "description": description, "owner": "coordinator-1",
            "due_at": due_at, "continue_on": "confirmed_outcome"}


def outcome(event_id, description):
    return {"source": "staff_form", "event_id": event_id, "physician_id": "doctor-1",
            "confirmed_at": "2026-10-03T13:00:00+00:00", "summary": "Synthetic physician decision",
            "next_steps": [next_step(description)]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = EpisodeStore(Path(self.tmp.name) / "db.sqlite3", Ruleset(Path(__file__).with_name("rules.json")))
        self.addCleanup(self.store.close)
        self.episode, _ = self.store.ingest(report())
        self.episode = self.store.add_manual_plan(self.episode.id, "doctor-1",
                                                   [{"kind": "appointment", "description": "First consultation"}])

    def visit(self, step_id):
        for action in ("offer", "confirm", "attend"):
            self.episode = self.store.transition(self.episode.id, step_id, action, "coordinator-1",
                evidence="Synthetic fixture", appointment_at="2026-10-04T10:00:00+00:00" if action == "offer" else None)

    def test_two_cycles_replay_and_close(self):
        first = self.episode.plan_steps[1].id
        with self.assertRaises(ConflictError):
            self.store.confirmed_outcome(self.episode.id, first, outcome("visit-1", "Second consultation"))
        self.visit(first)
        self.episode, duplicate = self.store.confirmed_outcome(self.episode.id, first, outcome("visit-1", "Second consultation"))
        self.assertFalse(duplicate)
        same, duplicate = self.store.confirmed_outcome(self.episode.id, first, outcome("visit-1", "Second consultation"))
        self.assertTrue(duplicate)
        self.assertEqual(len(same.plan_steps), 3)
        with self.assertRaises(ConflictError):
            self.store.confirmed_outcome(self.episode.id, first, outcome("visit-1", "Changed"))
        second = same.plan_steps[-1]
        self.assertEqual(second.cycle, 2)
        self.assertIn("visit-1", second.decision_source)
        self.visit(second.id)
        last = outcome("visit-2", "unused")
        last["next_steps"] = []
        self.episode, _ = self.store.confirmed_outcome(self.episode.id, second.id, last)
        self.assertEqual(self.store.close_episode(self.episode.id, "doctor-1", "Plan completed").status, "completed")
        self.assertEqual(self.store.metrics()["attended_visits"], 2)
        self.assertEqual(len(self.store.patient_view("patient-1")[0]["plan_history"]), 3)

    def test_pause_revision_and_queue(self):
        step = self.episode.plan_steps[1]
        self.episode = self.store.transition(self.episode.id, step.id, "offer", "coordinator-1",
            evidence="Offered", appointment_at="2026-10-04T10:00:00+00:00", due_at="2026-10-01T10:00:00+00:00")
        self.assertIn("overdue:" + step.id, self.store.coordinator_queue("2026-10-03T10:00:00+00:00")[0]["reasons"])
        self.episode = self.store.transition(self.episode.id, step.id, "refuse", "coordinator-1", evidence="Patient declined")
        self.assertEqual(self.episode.status, "paused")
        with self.assertRaises(ConflictError):
            self.store.transition(self.episode.id, step.id, "confirm", "coordinator-1", evidence="Invalid")
        self.episode = self.store.revise_plan(self.episode.id, "doctor-1", "Patient requested another date",
                                               [next_step("Revised consultation")])
        self.assertEqual(self.episode.plan_steps[1].status, "superseded")
        self.assertEqual(self.episode.plan_steps[-1].status, "open")
        self.assertEqual(self.episode.status, "active")
        self.assertGreater(len(self.store.outbox()), 1)

    def test_cancel_lost_contact_and_closure(self):
        step = self.episode.plan_steps[1]
        self.episode = self.store.transition(self.episode.id, step.id, "offer", "coordinator-1",
            evidence="Offered", appointment_at="2026-10-04T10:00:00+00:00")
        self.episode = self.store.transition(self.episode.id, step.id, "confirm", "coordinator-1", evidence="Confirmed")
        self.episode = self.store.transition(self.episode.id, step.id, "cancel", "coordinator-1", evidence="Cancelled by clinic")
        self.assertEqual(self.episode.status, "paused")
        self.episode = self.store.revise_plan(self.episode.id, "doctor-1", "Reschedule", [next_step("New slot")])
        active = self.episode.plan_steps[-1]
        self.episode = self.store.transition(self.episode.id, active.id, "lost_contact", "coordinator-1",
                                              evidence="No response")
        self.assertEqual(self.episode.manual_reason, "lost_contact")
        self.assertEqual(self.store.stop_episode(self.episode.id, "coordinator-1", "Unable to reach patient").status, "closed")
        with self.assertRaises(ConflictError):
            self.store.revise_plan(self.episode.id, "doctor-1", "Too late", [next_step("Another")])


if __name__ == "__main__":
    unittest.main()
