ALTER TABLE appointments ALTER COLUMN episode_id DROP NOT NULL;
ALTER TABLE appointments ALTER COLUMN step_id DROP NOT NULL;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS service_code text;
CREATE INDEX IF NOT EXISTS appointments_patient ON appointments (patient_ref);
