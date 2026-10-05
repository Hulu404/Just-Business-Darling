CREATE TABLE IF NOT EXISTS plain_texts (
  job_id text PRIMARY KEY,
  body text NOT NULL,
  physician_id text NOT NULL,
  lost_facts boolean NOT NULL DEFAULT false,
  approved_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE plain_texts ENABLE ROW LEVEL SECURITY;
