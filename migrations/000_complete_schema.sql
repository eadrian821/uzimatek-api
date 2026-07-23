-- ============================================================
-- Uzimatek Complete Schema — run this ONCE in Supabase SQL editor
-- https://supabase.com/dashboard/project/wpjoyfzysbftnbmkstxb/sql/new
--
-- Idempotent: safe to run multiple times (IF NOT EXISTS, ON CONFLICT DO NOTHING)
-- Combines: 001_sha_claims + 002_ehr_tables + 003_disable_rls
-- ============================================================


-- ── SHA Claims ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS patients (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  facility_id           TEXT NOT NULL,
  sha_member_id         TEXT,
  id_number             TEXT,
  name                  TEXT NOT NULL,
  dob                   DATE,
  gender                TEXT,
  scheme                TEXT DEFAULT 'SHIF',
  eligibility_status    TEXT DEFAULT 'unknown',
  eligibility_checked_at TIMESTAMPTZ,
  ward                  TEXT,
  bed                   TEXT,
  admitted_at           DATE,
  attending             TEXT,
  risk                  TEXT DEFAULT 'low',
  avatar_color          TEXT,
  created_at            TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_patients_facility   ON patients(facility_id);
CREATE INDEX IF NOT EXISTS idx_patients_sha_member ON patients(sha_member_id);
CREATE INDEX IF NOT EXISTS idx_patients_id_number  ON patients(id_number);


CREATE TABLE IF NOT EXISTS sha_claims (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id       TEXT NOT NULL UNIQUE,
  facility_id    TEXT NOT NULL,
  patient_id     UUID REFERENCES patients(id),
  sha_ref        TEXT,
  scheme         TEXT NOT NULL DEFAULT 'SHIF',
  encounter_type TEXT NOT NULL DEFAULT 'outpatient',
  service_date   DATE NOT NULL,
  icd_codes      TEXT[] DEFAULT '{}',
  tariff_codes   TEXT[] DEFAULT '{}',
  claim_amount   DECIMAL(12,2),
  approved_amount DECIMAL(12,2),
  status         TEXT NOT NULL DEFAULT 'draft',
  pipeline_status JSONB DEFAULT '{}',
  ebv_result     JSONB,
  paa_result     JSONB,
  cce_result     JSONB,
  fadcpe_result  JSONB,
  ri_result      JSONB,
  sha_payload    JSONB,
  sha_response   JSONB,
  created_at     TIMESTAMPTZ DEFAULT now(),
  updated_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sha_claims_facility     ON sha_claims(facility_id);
CREATE INDEX IF NOT EXISTS idx_sha_claims_status       ON sha_claims(status);
CREATE INDEX IF NOT EXISTS idx_sha_claims_service_date ON sha_claims(service_date DESC);
CREATE INDEX IF NOT EXISTS idx_sha_claims_sha_ref      ON sha_claims(sha_ref);


CREATE TABLE IF NOT EXISTS claim_events (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id         TEXT NOT NULL,
  facility_id      TEXT NOT NULL,
  event_type       TEXT NOT NULL,
  timestamp        TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload          JSONB NOT NULL DEFAULT '{}',
  agent_predictions JSONB,
  sha_data         JSONB
);
CREATE INDEX IF NOT EXISTS idx_claim_events_claim_id   ON claim_events(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_events_facility   ON claim_events(facility_id);
CREATE INDEX IF NOT EXISTS idx_claim_events_event_type ON claim_events(event_type);
CREATE INDEX IF NOT EXISTS idx_claim_events_timestamp  ON claim_events(timestamp DESC);


CREATE TABLE IF NOT EXISTS sha_adjudications (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id         TEXT NOT NULL UNIQUE,
  facility_id      TEXT NOT NULL,
  sha_ref          TEXT,
  outcome          TEXT NOT NULL,
  rejection_code   TEXT,
  adjudication_date DATE,
  payment_amount   DECIMAL(12,2),
  payment_date     DATE,
  appeal_outcome   TEXT,
  created_at       TIMESTAMPTZ DEFAULT now(),
  updated_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sha_adjudications_facility       ON sha_adjudications(facility_id);
CREATE INDEX IF NOT EXISTS idx_sha_adjudications_outcome        ON sha_adjudications(outcome);
CREATE INDEX IF NOT EXISTS idx_sha_adjudications_rejection_code ON sha_adjudications(rejection_code);


CREATE TABLE IF NOT EXISTS tariff_confidence_matrix (
  icd_code         TEXT NOT NULL,
  sha_tariff_code  TEXT NOT NULL,
  n_submissions    INTEGER DEFAULT 0,
  n_approved       INTEGER DEFAULT 0,
  n_rejected_e006  INTEGER DEFAULT 0,
  last_updated     DATE DEFAULT CURRENT_DATE,
  PRIMARY KEY (icd_code, sha_tariff_code)
);


-- Trigger: update tariff matrix when adjudication lands
CREATE OR REPLACE FUNCTION update_tariff_matrix()
RETURNS TRIGGER AS $$
DECLARE
  icd    TEXT;
  tariff TEXT;
BEGIN
  SELECT unnest(icd_codes), unnest(tariff_codes)
  INTO icd, tariff
  FROM sha_claims WHERE claim_id = NEW.claim_id LIMIT 1;

  IF icd IS NOT NULL AND tariff IS NOT NULL THEN
    INSERT INTO tariff_confidence_matrix
      (icd_code, sha_tariff_code, n_submissions, n_approved, n_rejected_e006, last_updated)
    VALUES (
      icd, tariff, 1,
      CASE WHEN NEW.outcome = 'approved' THEN 1 ELSE 0 END,
      CASE WHEN NEW.rejection_code = 'E006' THEN 1 ELSE 0 END,
      CURRENT_DATE
    )
    ON CONFLICT (icd_code, sha_tariff_code) DO UPDATE SET
      n_submissions   = tariff_confidence_matrix.n_submissions + 1,
      n_approved      = tariff_confidence_matrix.n_approved + CASE WHEN NEW.outcome = 'approved' THEN 1 ELSE 0 END,
      n_rejected_e006 = tariff_confidence_matrix.n_rejected_e006 + CASE WHEN NEW.rejection_code = 'E006' THEN 1 ELSE 0 END,
      last_updated    = CURRENT_DATE;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_tariff_matrix ON sha_adjudications;
CREATE TRIGGER trg_update_tariff_matrix
  AFTER INSERT ON sha_adjudications
  FOR EACH ROW EXECUTE FUNCTION update_tariff_matrix();


-- ── EHR Clinical Tables ────────────────────────────────────

CREATE TABLE IF NOT EXISTS problems (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  icd_code   TEXT NOT NULL,
  name       TEXT NOT NULL,
  severity   TEXT DEFAULT 'mild',
  since      TEXT,
  status     TEXT DEFAULT 'Active',
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_problems_patient ON problems(patient_id);


CREATE TABLE IF NOT EXISTS vitals (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id       UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  bp_systolic      INTEGER,
  bp_diastolic     INTEGER,
  heart_rate       INTEGER,
  spo2             NUMERIC(4,1),
  temperature      NUMERIC(4,1),
  respiratory_rate INTEGER,
  created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vitals_patient  ON vitals(patient_id);
CREATE INDEX IF NOT EXISTS idx_vitals_recorded ON vitals(recorded_at DESC);


CREATE TABLE IF NOT EXISTS labs (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  test_name  TEXT NOT NULL,
  value      TEXT NOT NULL,
  unit       TEXT,
  ref_range  TEXT,
  flag       TEXT,
  test_date  DATE NOT NULL DEFAULT CURRENT_DATE,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_labs_patient ON labs(patient_id);


CREATE TABLE IF NOT EXISTS medications (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  dose       TEXT NOT NULL,
  frequency  TEXT DEFAULT 'OD',
  route      TEXT DEFAULT 'PO',
  indication TEXT,
  start_year TEXT,
  active     BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_medications_patient ON medications(patient_id);


CREATE TABLE IF NOT EXISTS clinical_notes (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  note_type  TEXT DEFAULT 'Progress',
  author     TEXT,
  soap_text  TEXT NOT NULL,
  note_date  DATE NOT NULL DEFAULT CURRENT_DATE,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notes_patient ON clinical_notes(patient_id);
CREATE INDEX IF NOT EXISTS idx_notes_date    ON clinical_notes(note_date DESC);


CREATE TABLE IF NOT EXISTS tasks (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  label      TEXT NOT NULL,
  due        TEXT,
  done       BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tasks_patient ON tasks(patient_id);


CREATE TABLE IF NOT EXISTS training_outcomes (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id               TEXT NOT NULL,
  facility_id            TEXT NOT NULL,
  sha_ref                TEXT,
  actual_outcome         TEXT NOT NULL,
  rejection_code         TEXT,
  actual_payment_kes     NUMERIC(12,2),
  days_to_payment        INTEGER,
  fadcpe_predicted_risk  TEXT,
  fadcpe_predicted_score NUMERIC(4,3),
  ri_predicted_rate      NUMERIC(4,3),
  ri_predicted_days      INTEGER,
  cce_tariff_codes       TEXT[],
  notes                  TEXT,
  created_at             TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_training_claim    ON training_outcomes(claim_id);
CREATE INDEX IF NOT EXISTS idx_training_facility ON training_outcomes(facility_id);
CREATE INDEX IF NOT EXISTS idx_training_outcome  ON training_outcomes(actual_outcome);


-- ── Seed: tariff confidence matrix (known good mappings) ──

INSERT INTO tariff_confidence_matrix (icd_code, sha_tariff_code, n_submissions, n_approved) VALUES
  ('J18.9', 'SHA-RESP-001',    10, 9),
  ('I10',   'SHA-CVD-001',     15, 14),
  ('E11.9', 'SHA-META-001',    12, 11),
  ('B50',   'SHA-INF-001',     20, 19),
  ('N39.0', 'SHA-INF-003',      8,  7),
  ('A09',   'SHA-GI-001',      18, 17),
  ('Z34.9', 'SHA-MCH-001',     25, 25),
  ('O80',   'SHA-MCH-002',     30, 28),
  ('O82.9', 'SHA-MCH-003',      5,  4),
  ('Z00.0', 'SHA-CONSULT-001', 50, 48),
  ('K35.9', 'SHA-SURG-001',     8,  7),
  ('I50.9', 'SHA-CVD-002',      6,  5),
  ('N18.3', 'SHA-RENAL-001',   10,  9),
  ('E11.65','SHA-META-003',     4,  3),
  ('B20',   'SHA-INF-004',      9,  8)
ON CONFLICT DO NOTHING;


-- ── Seed: James Ochieng Otieno (demo patient for DHABP00301) ─

INSERT INTO patients (
  id, facility_id, sha_member_id, id_number, name, dob, gender, scheme,
  ward, bed, admitted_at, attending, risk, eligibility_status
) VALUES (
  '00000000-0000-0000-0000-000000000001',
  'DHABP00301',
  'SHA-2201-8845-90',
  '23456789',
  'James Ochieng Otieno',
  '1968-03-14',
  'M',
  'SHIF',
  'Ward 4B', '4B-07',
  '2026-07-17',
  'Dr. B. Achieng',
  'high',
  'eligible'
) ON CONFLICT (id) DO NOTHING;


INSERT INTO problems (patient_id, icd_code, name, severity, since, status) VALUES
  ('00000000-0000-0000-0000-000000000001', 'I10',   'Hypertensive heart disease',       'critical', '2019', 'Active · uncontrolled'),
  ('00000000-0000-0000-0000-000000000001', 'N18.3', 'Chronic kidney disease stage 3b',  'moderate', '2023', 'Active · monitoring'),
  ('00000000-0000-0000-0000-000000000001', 'E11.9', 'Type 2 diabetes mellitus',         'moderate', '2016', 'Active · poor control'),
  ('00000000-0000-0000-0000-000000000001', 'G63.2', 'Diabetic peripheral neuropathy',   'mild',     '2025', 'Active · new')
ON CONFLICT DO NOTHING;


INSERT INTO vitals (patient_id, recorded_at, bp_systolic, bp_diastolic, heart_rate, spo2, temperature, respiratory_rate) VALUES
  ('00000000-0000-0000-0000-000000000001', '2026-07-19 05:00:00+00', 198, 112, 96, 93.0, 37.1, 22),
  ('00000000-0000-0000-0000-000000000001', '2026-07-19 09:00:00+00', 182, 104, 90, 94.0, 36.9, 20),
  ('00000000-0000-0000-0000-000000000001', '2026-07-19 13:00:00+00', 174,  98, 88, 94.0, 36.8, 19),
  ('00000000-0000-0000-0000-000000000001', '2026-07-19 17:00:00+00', 168,  96, 86, 95.0, 36.7, 18);


INSERT INTO labs (patient_id, test_name, value, unit, ref_range, flag, test_date) VALUES
  ('00000000-0000-0000-0000-000000000001', 'Creatinine',  '148',  'µmol/L',        '62–106',  'H', '2026-07-19'),
  ('00000000-0000-0000-0000-000000000001', 'eGFR',        '44',   'mL/min/1.73m²', '>90',     'L', '2026-07-19'),
  ('00000000-0000-0000-0000-000000000001', 'HbA1c',       '11.4', '%',             '<6.5',    'H', '2026-07-19'),
  ('00000000-0000-0000-0000-000000000001', 'Potassium',   '5.1',  'mmol/L',        '3.5–5.0', 'H', '2026-07-19'),
  ('00000000-0000-0000-0000-000000000001', 'Haemoglobin', '11.2', 'g/dL',          '13–17',   'L', '2026-07-19'),
  ('00000000-0000-0000-0000-000000000001', 'UACR',        '68',   'mg/mmol',       '<3',      'H', '2026-07-19')
ON CONFLICT DO NOTHING;


INSERT INTO medications (patient_id, name, dose, frequency, route, indication, start_year) VALUES
  ('00000000-0000-0000-0000-000000000001', 'Amlodipine', '10mg', 'OD', 'PO', 'HTN',     '2019'),
  ('00000000-0000-0000-0000-000000000001', 'Metformin',  '1g',   'BD', 'PO', 'T2DM',    '2016'),
  ('00000000-0000-0000-0000-000000000001', 'Losartan',   '50mg', 'OD', 'PO', 'HTN/CKD', '2021'),
  ('00000000-0000-0000-0000-000000000001', 'Furosemide', '40mg', 'OD', 'PO', 'Oedema',  '2024')
ON CONFLICT DO NOTHING;


INSERT INTO clinical_notes (patient_id, note_type, author, soap_text, note_date) VALUES
  ('00000000-0000-0000-0000-000000000001', 'Progress', 'Dr. B. Achieng',
   'S: BP not controlled. Headache persisting.
O: BP 174/98, HR 88, SpO2 94%.
A: Hypertensive urgency, improving.
P: Continue IV fluids, repeat UEC tomorrow.',
   '2026-07-19'),
  ('00000000-0000-0000-0000-000000000001', 'Admission', 'Dr. B. Achieng',
   'S: Severe headache, blurred vision x2 days.
O: BP 198/112, HR 96, SpO2 93%. CXR: CTR 0.58.
A: Hypertensive heart disease + CKD 3b + T2DM.
P: Admit Ward 4B. IV hydralazine, urine catheter, UEC, ECG.',
   '2026-07-17')
ON CONFLICT DO NOTHING;


INSERT INTO tasks (patient_id, label, due, done) VALUES
  ('00000000-0000-0000-0000-000000000001', 'ECHO cardiogram',            'Today',     false),
  ('00000000-0000-0000-0000-000000000001', 'Renal ultrasound',           'Tomorrow',  false),
  ('00000000-0000-0000-0000-000000000001', 'Ophthalmology referral',     'In 5 days', false),
  ('00000000-0000-0000-0000-000000000001', 'Start ACEi dose adjustment', 'Today',     true),
  ('00000000-0000-0000-0000-000000000001', 'Repeat UEC in 48h',          'In 2 days', false)
ON CONFLICT DO NOTHING;


-- ── Seed: second demo patient ─────────────────────────────

INSERT INTO patients (
  id, facility_id, sha_member_id, id_number, name, dob, gender, scheme,
  ward, bed, admitted_at, attending, risk, eligibility_status
) VALUES (
  '00000000-0000-0000-0000-000000000002',
  'DHABP00301',
  'SHA-3301-7732-11',
  '34567890',
  'Grace Akinyi Njeri',
  '1997-08-22',
  'F',
  'LINDA_MAMA',
  'Maternity', 'MAT-04',
  '2026-07-22',
  'Dr. B. Achieng',
  'high',
  'eligible'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO problems (patient_id, icd_code, name, severity, since, status) VALUES
  ('00000000-0000-0000-0000-000000000002', 'O14.1', 'Severe pre-eclampsia', 'critical', '2026', 'Active · on MgSO₄'),
  ('00000000-0000-0000-0000-000000000002', 'O60',   'Preterm labour 34wks', 'moderate', '2026', 'Active · monitoring')
ON CONFLICT DO NOTHING;

INSERT INTO vitals (patient_id, recorded_at, bp_systolic, bp_diastolic, heart_rate, spo2, temperature) VALUES
  ('00000000-0000-0000-0000-000000000002', '2026-07-22 07:00:00+00', 162, 108, 102, 97.0, 37.3),
  ('00000000-0000-0000-0000-000000000002', '2026-07-22 12:00:00+00', 148,  98,  98, 97.5, 37.1);

INSERT INTO tasks (patient_id, label, due, done) VALUES
  ('00000000-0000-0000-0000-000000000002', 'CTG monitoring',          'Continuous', false),
  ('00000000-0000-0000-0000-000000000002', 'MgSO₄ 4th hourly review', 'Every 4h',  false),
  ('00000000-0000-0000-0000-000000000002', 'Neonatology consult',     'Today',      false),
  ('00000000-0000-0000-0000-000000000002', 'Betamethasone x2 doses',  'Today',      true)
ON CONFLICT DO NOTHING;


-- ── Seed: third demo patient ──────────────────────────────

INSERT INTO patients (
  id, facility_id, sha_member_id, id_number, name, dob, gender, scheme,
  ward, bed, admitted_at, attending, risk, eligibility_status
) VALUES (
  '00000000-0000-0000-0000-000000000003',
  'DHABP00301',
  'SHA-4411-5521-77',
  '45678901',
  'Peter Kariuki Mwangi',
  '1981-04-10',
  'M',
  'SHIF',
  'Ward 4A', '4A-03',
  '2026-07-20',
  'Dr. B. Achieng',
  'medium',
  'eligible'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO problems (patient_id, icd_code, name, severity, since, status) VALUES
  ('00000000-0000-0000-0000-000000000003', 'E11.9', 'Type 2 diabetes mellitus',  'moderate', '2015', 'Active · on insulin'),
  ('00000000-0000-0000-0000-000000000003', 'L97.9', 'Diabetic foot ulcer R foot', 'moderate', '2026', 'Active · debrided')
ON CONFLICT DO NOTHING;

INSERT INTO vitals (patient_id, recorded_at, bp_systolic, bp_diastolic, heart_rate, spo2, temperature) VALUES
  ('00000000-0000-0000-0000-000000000003', '2026-07-22 08:00:00+00', 132, 82, 88, 96.0, 37.6);

INSERT INTO tasks (patient_id, label, due, done) VALUES
  ('00000000-0000-0000-0000-000000000003', 'Wound dressing change',  'Daily',     false),
  ('00000000-0000-0000-0000-000000000003', 'Vascular surgery review','Tomorrow',  false),
  ('00000000-0000-0000-0000-000000000003', 'HbA1c result review',    'Today',     true)
ON CONFLICT DO NOTHING;


-- ── Disable Row Level Security (critical — anon key returns 0 rows with RLS) ─

ALTER TABLE patients                DISABLE ROW LEVEL SECURITY;
ALTER TABLE problems                DISABLE ROW LEVEL SECURITY;
ALTER TABLE vitals                  DISABLE ROW LEVEL SECURITY;
ALTER TABLE labs                    DISABLE ROW LEVEL SECURITY;
ALTER TABLE medications             DISABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_notes          DISABLE ROW LEVEL SECURITY;
ALTER TABLE tasks                   DISABLE ROW LEVEL SECURITY;
ALTER TABLE training_outcomes       DISABLE ROW LEVEL SECURITY;
ALTER TABLE sha_claims              DISABLE ROW LEVEL SECURITY;
ALTER TABLE claim_events            DISABLE ROW LEVEL SECURITY;
ALTER TABLE sha_adjudications       DISABLE ROW LEVEL SECURITY;
ALTER TABLE tariff_confidence_matrix DISABLE ROW LEVEL SECURITY;


-- ── Verify ───────────────────────────────────────────────

SELECT 'patients'             AS tbl, COUNT(*) AS n FROM patients WHERE facility_id = 'DHABP00301'
UNION ALL
SELECT 'problems',  COUNT(*) FROM problems
UNION ALL
SELECT 'vitals',    COUNT(*) FROM vitals
UNION ALL
SELECT 'labs',      COUNT(*) FROM labs
UNION ALL
SELECT 'medications', COUNT(*) FROM medications
UNION ALL
SELECT 'clinical_notes', COUNT(*) FROM clinical_notes
UNION ALL
SELECT 'tasks',     COUNT(*) FROM tasks
UNION ALL
SELECT 'sha_claims', COUNT(*) FROM sha_claims
UNION ALL
SELECT 'tariff_matrix', COUNT(*) FROM tariff_confidence_matrix;
-- Expected: patients=3, problems=8, vitals=7, labs=6, medications=4, notes=2, tasks=12, sha_claims=0, tariff_matrix=15
