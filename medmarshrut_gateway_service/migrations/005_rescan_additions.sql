CREATE TABLE IF NOT EXISTS patient_settings (
  patient_ref text PRIMARY KEY,
  settings_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE patient_settings ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS self_medications (
  id text PRIMARY KEY,
  patient_ref text NOT NULL,
  name text NOT NULL,
  dose text NOT NULL,
  time_slot text NOT NULL CHECK (time_slot IN ('morning', 'day', 'evening')),
  form text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS self_medications_patient ON self_medications (patient_ref);
ALTER TABLE self_medications ENABLE ROW LEVEL SECURITY;