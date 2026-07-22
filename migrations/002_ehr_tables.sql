-- EHR Clinical Data Tables — Uzimatek
-- Run in Supabase SQL editor: https://supabase.com/dashboard/project/wpjoyfzysbftnbmkstxb/sql/new
-- Run AFTER 001_sha_claims.sql

-- ── Extend the existing patients table ────────────────────────────────────────
ALTER TABLE patients
  ADD COLUMN IF NOT EXISTS ward        TEXT,
  ADD COLUMN IF NOT EXISTS bed         TEXT,
  ADD COLUMN IF NOT EXISTS admitted_at DATE,
  ADD COLUMN IF NOT EXISTS attending   TEXT,
  ADD COLUMN IF NOT EXISTS risk        TEXT DEFAULT 'low',
  ADD COLUMN IF NOT EXISTS avatar_color TEXT;

-- ── Problem list ──────────────────────────────────────────────────────────────
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

-- ── Vitals ────────────────────────────────────────────────────────────────────
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

-- ── Labs ──────────────────────────────────────────────────────────────────────
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

-- ── Medications ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS medications (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id  UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  dose        TEXT NOT NULL,
  frequency   TEXT DEFAULT 'OD',
  route       TEXT DEFAULT 'PO',
  indication  TEXT,
  start_year  TEXT,
  active      BOOLEAN DEFAULT true,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_medications_patient ON medications(patient_id);

-- ── Clinical notes (SOAP) ─────────────────────────────────────────────────────
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

-- ── Tasks ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  label      TEXT NOT NULL,
  due        TEXT,
  done       BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tasks_patient ON tasks(patient_id);

-- ── Training outcomes (real SHA feedback → agent calibration) ─────────────────
-- Log actual SHA decisions against what the pipeline predicted.
-- Feed this back into tariff_confidence_matrix and eventually fine-tuning.
CREATE TABLE IF NOT EXISTS training_outcomes (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id              TEXT NOT NULL,
  facility_id           TEXT NOT NULL,
  sha_ref               TEXT,
  actual_outcome        TEXT NOT NULL,        -- approved | rejected | partial
  rejection_code        TEXT,                  -- E001–E010
  actual_payment_kes    NUMERIC(12,2),
  days_to_payment       INTEGER,
  fadcpe_predicted_risk TEXT,                  -- what FADCPE predicted
  fadcpe_predicted_score NUMERIC(4,3),
  ri_predicted_rate     NUMERIC(4,3),
  ri_predicted_days     INTEGER,
  cce_tariff_codes      TEXT[],
  notes                 TEXT,
  created_at            TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_training_claim    ON training_outcomes(claim_id);
CREATE INDEX IF NOT EXISTS idx_training_facility ON training_outcomes(facility_id);
CREATE INDEX IF NOT EXISTS idx_training_outcome  ON training_outcomes(actual_outcome);

-- ── Seed: James Ochieng Otieno ────────────────────────────────────────────────

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
  ('00000000-0000-0000-0000-000000000001', 'N18.3', 'Chronic kidney disease, stage 3b', 'moderate', '2023', 'Active · monitoring'),
  ('00000000-0000-0000-0000-000000000001', 'E11.9', 'Type 2 diabetes mellitus',         'moderate', '2016', 'Active · poor control'),
  ('00000000-0000-0000-0000-000000000001', 'G63.2', 'Diabetic peripheral neuropathy',   'mild',     '2025', 'Active · new');

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
  ('00000000-0000-0000-0000-000000000001', 'UACR',        '68',   'mg/mmol',       '<3',      'H', '2026-07-19');

INSERT INTO medications (patient_id, name, dose, frequency, route, indication, start_year) VALUES
  ('00000000-0000-0000-0000-000000000001', 'Amlodipine', '10mg', 'OD', 'PO', 'HTN',     '2019'),
  ('00000000-0000-0000-0000-000000000001', 'Metformin',  '1g',   'BD', 'PO', 'T2DM',    '2016'),
  ('00000000-0000-0000-0000-000000000001', 'Losartan',   '50mg', 'OD', 'PO', 'HTN/CKD', '2021'),
  ('00000000-0000-0000-0000-000000000001', 'Furosemide', '40mg', 'OD', 'PO', 'Oedema',  '2024');

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
   '2026-07-17');

INSERT INTO tasks (patient_id, label, due, done) VALUES
  ('00000000-0000-0000-0000-000000000001', 'ECHO cardiogram',            'Today',     false),
  ('00000000-0000-0000-0000-000000000001', 'Renal ultrasound',           'Tomorrow',  false),
  ('00000000-0000-0000-0000-000000000001', 'Ophthalmology referral',     'In 5 days', false),
  ('00000000-0000-0000-0000-000000000001', 'Start ACEi dose adjustment', 'Today',     true),
  ('00000000-0000-0000-0000-000000000001', 'Repeat UEC in 48h',          'In 2 days', false);
