CREATE TABLE IF NOT EXISTS referral_links (
  referral_id text PRIMARY KEY,
  episode_id text NOT NULL,
  step_id text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS referral_links_step ON referral_links (episode_id, step_id);
ALTER TABLE referral_links ENABLE ROW LEVEL SECURITY;
