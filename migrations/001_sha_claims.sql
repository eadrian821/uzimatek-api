-- SHA Claims System migrations
-- Run against Supabase project SQL editor

CREATE TABLE IF NOT EXISTS patients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  facility_id TEXT NOT NULL,
  sha_member_id TEXT,
  id_number TEXT,
  name TEXT NOT NULL,
  dob DATE,
  gender TEXT,
  scheme TEXT DEFAULT 'SHIF',
  eligibility_status TEXT DEFAULT 'unknown',
  eligibility_checked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_patients_facility ON patients(facility_id);
CREATE INDEX IF NOT EXISTS idx_patients_sha_member ON patients(sha_member_id);
CREATE INDEX IF NOT EXISTS idx_patients_id_number ON patients(id_number);

CREATE TABLE IF NOT EXISTS sha_claims (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id TEXT NOT NULL UNIQUE,
  facility_id TEXT NOT NULL,
  patient_id UUID REFERENCES patients(id),
  sha_ref TEXT,
  scheme TEXT NOT NULL DEFAULT 'SHIF',
  encounter_type TEXT NOT NULL DEFAULT 'outpatient',
  service_date DATE NOT NULL,
  icd_codes TEXT[] DEFAULT '{}',
  tariff_codes TEXT[] DEFAULT '{}',
  claim_amount DECIMAL(12,2),
  approved_amount DECIMAL(12,2),
  status TEXT NOT NULL DEFAULT 'draft',
  pipeline_status JSONB DEFAULT '{}',
  ebv_result JSONB,
  paa_result JSONB,
  cce_result JSONB,
  fadcpe_result JSONB,
  ri_result JSONB,
  sha_payload JSONB,
  sha_response JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sha_claims_facility ON sha_claims(facility_id);
CREATE INDEX IF NOT EXISTS idx_sha_claims_status ON sha_claims(status);
CREATE INDEX IF NOT EXISTS idx_sha_claims_service_date ON sha_claims(service_date DESC);
CREATE INDEX IF NOT EXISTS idx_sha_claims_sha_ref ON sha_claims(sha_ref);

CREATE TABLE IF NOT EXISTS claim_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id TEXT NOT NULL,
  facility_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL DEFAULT '{}',
  agent_predictions JSONB,
  sha_data JSONB
);
CREATE INDEX IF NOT EXISTS idx_claim_events_claim_id ON claim_events(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_events_facility_id ON claim_events(facility_id);
CREATE INDEX IF NOT EXISTS idx_claim_events_event_type ON claim_events(event_type);
CREATE INDEX IF NOT EXISTS idx_claim_events_timestamp ON claim_events(timestamp DESC);

CREATE TABLE IF NOT EXISTS sha_adjudications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id TEXT NOT NULL UNIQUE,
  facility_id TEXT NOT NULL,
  sha_ref TEXT,
  outcome TEXT NOT NULL,
  rejection_code TEXT,
  adjudication_date DATE,
  payment_amount DECIMAL(12,2),
  payment_date DATE,
  appeal_outcome TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sha_adjudications_facility ON sha_adjudications(facility_id);
CREATE INDEX IF NOT EXISTS idx_sha_adjudications_outcome ON sha_adjudications(outcome);
CREATE INDEX IF NOT EXISTS idx_sha_adjudications_rejection_code ON sha_adjudications(rejection_code);

CREATE TABLE IF NOT EXISTS tariff_confidence_matrix (
  icd_code TEXT NOT NULL,
  sha_tariff_code TEXT NOT NULL,
  n_submissions INTEGER DEFAULT 0,
  n_approved INTEGER DEFAULT 0,
  n_rejected_e006 INTEGER DEFAULT 0,
  last_updated DATE DEFAULT CURRENT_DATE,
  PRIMARY KEY (icd_code, sha_tariff_code)
);

-- Function to update tariff matrix after adjudication
CREATE OR REPLACE FUNCTION update_tariff_matrix()
RETURNS TRIGGER AS $$
DECLARE
  icd TEXT;
  tariff TEXT;
BEGIN
  -- Pull ICD and tariff codes from the parent claim
  SELECT unnest(icd_codes), unnest(tariff_codes)
  INTO icd, tariff
  FROM sha_claims WHERE claim_id = NEW.claim_id LIMIT 1;

  IF icd IS NOT NULL AND tariff IS NOT NULL THEN
    INSERT INTO tariff_confidence_matrix (icd_code, sha_tariff_code, n_submissions, n_approved, n_rejected_e006, last_updated)
    VALUES (icd, tariff, 1,
      CASE WHEN NEW.outcome = 'approved' THEN 1 ELSE 0 END,
      CASE WHEN NEW.rejection_code = 'E006' THEN 1 ELSE 0 END,
      CURRENT_DATE)
    ON CONFLICT (icd_code, sha_tariff_code) DO UPDATE SET
      n_submissions = tariff_confidence_matrix.n_submissions + 1,
      n_approved = tariff_confidence_matrix.n_approved + CASE WHEN NEW.outcome = 'approved' THEN 1 ELSE 0 END,
      n_rejected_e006 = tariff_confidence_matrix.n_rejected_e006 + CASE WHEN NEW.rejection_code = 'E006' THEN 1 ELSE 0 END,
      last_updated = CURRENT_DATE;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_update_tariff_matrix
  AFTER INSERT ON sha_adjudications
  FOR EACH ROW EXECUTE FUNCTION update_tariff_matrix();

-- Seed initial tariff matrix with known good mappings
INSERT INTO tariff_confidence_matrix (icd_code, sha_tariff_code, n_submissions, n_approved) VALUES
  ('J18.9', 'SHA-RESP-001', 10, 9),
  ('I10',   'SHA-CVD-001',  15, 14),
  ('E11.9', 'SHA-META-001', 12, 11),
  ('B50',   'SHA-INF-001',  20, 19),
  ('N39.0', 'SHA-INF-004',   8,  7),
  ('A09',   'SHA-GI-001',   18, 17),
  ('Z34.9', 'SHA-MCH-001',  25, 25),
  ('O80',   'SHA-MCH-002',  30, 28),
  ('O82.9', 'SHA-MCH-003',   5,  4),
  ('Z00.0', 'SHA-CONSULT-001', 50, 48)
ON CONFLICT DO NOTHING;
