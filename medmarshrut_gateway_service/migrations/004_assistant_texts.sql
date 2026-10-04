CREATE TABLE IF NOT EXISTS assistant_texts (
  job_id text NOT NULL,
  input_hash text NOT NULL,
  model text NOT NULL,
  body text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, input_hash)
);
ALTER TABLE assistant_texts ENABLE ROW LEVEL SECURITY;
