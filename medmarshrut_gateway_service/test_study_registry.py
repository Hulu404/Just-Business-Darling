"""study_registry on a real PostgreSQL, in throwaway schemas. Runs only with GATEWAY_TEST_DATABASE_URL set
(and GATEWAY_TEST_SUPABASE_PROJECT_REF, or "local" for 127.0.0.1); otherwise skipped."""
from __future__ import annotations

import os
import secrets
import unittest
from datetime import datetime, timezone

import migrate
from store import GatewayStore, StoreConflict

DSN = os.environ.get("GATEWAY_TEST_DATABASE_URL", "")
REF = os.environ.get("GATEWAY_TEST_SUPABASE_PROJECT_REF", "local")


@unittest.skipUnless(DSN, "нет GATEWAY_TEST_DATABASE_URL: тесты PostgreSQL пропущены")
class StudyRegistryTests(unittest.TestCase):
    def schema(self) -> GatewayStore:
        name = "mm_test_" + secrets.token_hex(4)
        migrate.run("apply", {"GATEWAY_DATABASE_URL": DSN, "GATEWAY_DB_SCHEMA": name, "GATEWAY_SUPABASE_PROJECT_REF": REF})
        store = GatewayStore(DSN, name)
        self.addCleanup(self.drop, store, name)
        store.verify_schema()
        return store

    @staticmethod
    def drop(store: GatewayStore, name: str) -> None:
        with store.db.cursor() as cur:
            cur.execute(f'DROP SCHEMA "{name}" CASCADE')
        store.close()

    def register(self, store, job_id="job-1", ref="demo-patient-1", **extra):
        values = {"clinic_id": "clinic-central", "patient_ref": ref, "task": "ct_general", "title": "КТ", "kit": None,
                  "uploaded_by_role": "patient", "uploaded_by": ref, "consent_at": datetime.now(timezone.utc)}
        values.update(extra)
        return store.register_study(job_id, **values)

    def test_migration_creates_table_with_rls_and_no_policies(self):
        store = self.schema()
        with store.db.cursor() as cur:
            cur.execute("SELECT c.relrowsecurity, (SELECT count(*) FROM pg_policies p WHERE p.schemaname=%s "
                        "AND p.tablename='study_registry') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=%s AND c.relname='study_registry'", (store.schema, store.schema))
            self.assertEqual(cur.fetchone(), (True, 0))
            cur.execute("SELECT version FROM schema_migrations ORDER BY version")
            self.assertEqual([r[0] for r in cur.fetchall()], sorted(f.stem for f in migrate.MIGRATIONS.glob("[0-9]*.sql")))

    def test_repeat_registration_is_idempotent_and_other_owner_conflicts(self):
        store = self.schema()
        first = self.register(store)
        self.assertEqual(self.register(store), first)
        self.assertEqual(len(store.studies("clinic-central")), 1)
        with self.assertRaises(StoreConflict):
            self.register(store, ref="demo-patient-2")

    def test_other_patient_and_other_clinic_rows_are_not_returned(self):
        store = self.schema()
        self.register(store, "job-1", "demo-patient-1")
        self.register(store, "job-2", "demo-patient-2")
        self.register(store, "job-3", "demo-patient-1", clinic_id="clinic-partner-1")
        self.assertEqual([r["job_id"] for r in store.studies("clinic-central", "demo-patient-1")], ["job-1"])
        self.assertIsNone(store.study("clinic-central", "job-3"))

    def test_referral_links_idempotent_isolated_cleared_and_kept(self):
        first, second = self.schema(), self.schema()
        link = first.link_referral("ref-1", "ep-1", "s1", "coordinator-natalia")
        self.assertEqual(first.link_referral("ref-1", "ep-1", "s1", "coordinator-natalia"), link)
        with self.assertRaises(StoreConflict):
            first.link_referral("ref-1", "ep-2", "s9", "coordinator-natalia")
        self.assertEqual(second.referral_links(), {})
        first.seed_catalog("clinic-central")  # the catalogue reset of a --keep start leaves links alone
        self.assertEqual(first.referral_links(["ref-1"]), {"ref-1": {"episode_id": "ep-1", "step_id": "s1"}})
        first.clear_working()  # a clean start
        self.assertEqual(first.referral_links(), {})

    def test_schemas_are_isolated_and_clean_start_clears_the_registry(self):
        first, second = self.schema(), self.schema()
        self.register(first)
        self.assertIsNone(second.study("clinic-central", "job-1"))
        first.clear_working()
        self.assertEqual(first.studies("clinic-central"), [])


if __name__ == "__main__":
    unittest.main()
