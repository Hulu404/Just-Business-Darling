CREATE TABLE IF NOT EXISTS study_registry (
  job_id text PRIMARY KEY,
  clinic_id text NOT NULL,
  patient_ref text,
  task text NOT NULL,
  title text,
  kit text,
  uploaded_by_role text NOT NULL CHECK (uploaded_by_role IN ('patient', 'staff')),
  uploaded_by text NOT NULL,
  consent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS study_registry_patient ON study_registry (clinic_id, patient_ref);
ALTER TABLE study_registry ENABLE ROW LEVEL SECURITY;
