-- Fix: disable RLS on all EHR tables so the anon/publishable key can read them.
-- Supabase enables RLS by default — without policies the anon key returns 0 rows.

ALTER TABLE patients           DISABLE ROW LEVEL SECURITY;
ALTER TABLE problems           DISABLE ROW LEVEL SECURITY;
ALTER TABLE vitals             DISABLE ROW LEVEL SECURITY;
ALTER TABLE labs               DISABLE ROW LEVEL SECURITY;
ALTER TABLE medications        DISABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_notes     DISABLE ROW LEVEL SECURITY;
ALTER TABLE tasks              DISABLE ROW LEVEL SECURITY;
ALTER TABLE training_outcomes  DISABLE ROW LEVEL SECURITY;

-- Also disable on SHA claims tables
ALTER TABLE sha_claims              DISABLE ROW LEVEL SECURITY;
ALTER TABLE claim_events            DISABLE ROW LEVEL SECURITY;
ALTER TABLE sha_adjudications       DISABLE ROW LEVEL SECURITY;
ALTER TABLE tariff_confidence_matrix DISABLE ROW LEVEL SECURITY;

-- Verify seed data landed
SELECT 'patients' as tbl, COUNT(*) as n FROM patients WHERE facility_id = 'DHABP00301'
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
SELECT 'tasks',     COUNT(*) FROM tasks;
