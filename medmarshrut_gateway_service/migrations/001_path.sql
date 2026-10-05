CREATE TABLE IF NOT EXISTS services (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  clinic_id text NOT NULL,
  code text NOT NULL,
  title text NOT NULL,
  kind text NOT NULL,
  specialist text,
  room text,
  partner_only boolean NOT NULL DEFAULT false,
  step_aliases text[] NOT NULL DEFAULT '{}',
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (clinic_id, code)
);
CREATE TABLE IF NOT EXISTS service_followups (
  clinic_id text NOT NULL,
  finding_code text NOT NULL,
  service_code text NOT NULL,
  position integer NOT NULL CHECK (position > 0),
  due_days integer CHECK (due_days >= 0),
  due_note text,
  is_default boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (clinic_id, finding_code, service_code),
  UNIQUE (clinic_id, finding_code, position),
  FOREIGN KEY (clinic_id, service_code) REFERENCES services (clinic_id, code)
);
CREATE TABLE IF NOT EXISTS finding_texts (
  clinic_id text NOT NULL,
  finding_code text NOT NULL,
  seen text NOT NULL,
  means text NOT NULL,
  approved boolean NOT NULL DEFAULT false,
  approved_by text,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (clinic_id, finding_code)
);
CREATE TABLE IF NOT EXISTS slots (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  clinic_id text NOT NULL,
  service_id bigint NOT NULL REFERENCES services (id),
  specialist text NOT NULL,
  place text NOT NULL,
  format text NOT NULL,
  starts_at timestamptz NOT NULL,
  price numeric(12,2),
  external_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (clinic_id, service_id, specialist, starts_at)
);
CREATE TABLE IF NOT EXISTS appointments (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  episode_id text NOT NULL,
  step_id text NOT NULL,
  patient_ref text NOT NULL,
  slot_id bigint REFERENCES slots (id),
  clinic_id text NOT NULL,
  starts_at timestamptz NOT NULL,
  place text,
  format text NOT NULL,
  status text NOT NULL,
  booked_by text NOT NULL,
  booked_by_id text NOT NULL,
  referral_id text,
  external_id text,
  cancelled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS appointments_live_slot ON appointments (slot_id)
  WHERE slot_id IS NOT NULL AND status IN ('offered', 'confirmed');
CREATE UNIQUE INDEX IF NOT EXISTS appointments_live_step ON appointments (episode_id, step_id)
  WHERE status IN ('offered', 'confirmed');
CREATE TABLE IF NOT EXISTS threads (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('patient', 'staff')),
  clinic_id text NOT NULL,
  patient_ref text,
  episode_id text,
  subject text,
  request_kind text,
  status text NOT NULL DEFAULT 'open',
  opened_by_role text NOT NULL,
  opened_by text,
  closed_at timestamptz,
  closed_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_patient_thread ON threads (clinic_id, patient_ref)
  WHERE kind = 'patient';
CREATE TABLE IF NOT EXISTS messages (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  thread_id bigint NOT NULL REFERENCES threads (id),
  sender_role text NOT NULL,
  sender_id text,
  body text NOT NULL,
  event_code text,
  intent text,
  episode_id text,
  step_id text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  channel text NOT NULL DEFAULT 'app',
  for_patient boolean NOT NULL DEFAULT true,
  needs_action boolean NOT NULL DEFAULT false,
  resolved_at timestamptz,
  resolved_by text,
  dedupe_key text UNIQUE,
  read_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS outcome_submissions (
  event_id text PRIMARY KEY,
  episode_id text NOT NULL,
  step_id text NOT NULL,
  physician_id text NOT NULL,
  confirmed_at timestamptz NOT NULL,
  body_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE services ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_followups ENABLE ROW LEVEL SECURITY;
ALTER TABLE finding_texts ENABLE ROW LEVEL SECURITY;
ALTER TABLE slots ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE outcome_submissions ENABLE ROW LEVEL SECURITY;
