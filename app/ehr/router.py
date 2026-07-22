"""EHR REST API — patient chart CRUD + training feedback endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.ehr import db
from app.ehr.models import (
    LabCreate, MedicationCreate, NoteCreate, PatientCreate,
    ProblemCreate, TaskCreate, TaskToggle, TrainingOutcome, VitalsCreate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ehr", tags=["EHR"])

FACILITY_ID = "DHABP00301"


# ── Patients ──────────────────────────────────────────────────────────────────

@router.get("/patients")
async def list_patients(facility_id: str = Query(default=FACILITY_ID)):
    """List all patients for a facility with full embedded clinical data."""
    patients = await db.list_patients(facility_id)
    return {"patients": patients, "count": len(patients)}


@router.post("/patients", status_code=201)
async def create_patient(body: PatientCreate):
    """Admit a new patient and create their chart."""
    data = body.model_dump(exclude_none=True)
    patient = await db.create_patient(data)
    if not patient:
        raise HTTPException(status_code=500, detail="Failed to create patient in database.")
    return patient


@router.get("/patients/{patient_id}")
async def get_patient(patient_id: str):
    """Fetch a single patient's full chart (problems, vitals, labs, meds, notes, tasks)."""
    patient = await db.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


# ── Problems ──────────────────────────────────────────────────────────────────

@router.post("/patients/{patient_id}/problems", status_code=201)
async def add_problem(patient_id: str, body: ProblemCreate):
    return await db.add_problem(patient_id, body.model_dump(exclude_none=True))


@router.delete("/patients/{patient_id}/problems/{problem_id}", status_code=204)
async def delete_problem(patient_id: str, problem_id: str):
    await db.delete_problem(problem_id)


# ── Vitals ────────────────────────────────────────────────────────────────────

@router.post("/patients/{patient_id}/vitals", status_code=201)
async def add_vitals(patient_id: str, body: VitalsCreate):
    data = body.model_dump(exclude_none=True)
    if "recorded_at" in data and data["recorded_at"]:
        data["recorded_at"] = data["recorded_at"].isoformat()
    return await db.add_vitals(patient_id, data)


@router.get("/patients/{patient_id}/vitals")
async def list_vitals(patient_id: str):
    rows = await db.list_vitals(patient_id)
    return {"vitals": rows}


# ── Labs ──────────────────────────────────────────────────────────────────────

@router.post("/patients/{patient_id}/labs", status_code=201)
async def add_lab(patient_id: str, body: LabCreate):
    return await db.add_lab(patient_id, body.model_dump(exclude_none=True))


@router.delete("/patients/{patient_id}/labs/{lab_id}", status_code=204)
async def delete_lab(patient_id: str, lab_id: str):
    await db.delete_lab(lab_id)


# ── Medications ───────────────────────────────────────────────────────────────

@router.post("/patients/{patient_id}/medications", status_code=201)
async def add_medication(patient_id: str, body: MedicationCreate):
    return await db.add_medication(patient_id, body.model_dump(exclude_none=True))


@router.delete("/patients/{patient_id}/medications/{med_id}", status_code=204)
async def delete_medication(patient_id: str, med_id: str):
    await db.delete_medication(med_id)


# ── Notes ─────────────────────────────────────────────────────────────────────

@router.post("/patients/{patient_id}/notes", status_code=201)
async def add_note(patient_id: str, body: NoteCreate):
    return await db.add_note(patient_id, body.model_dump(exclude_none=True))


@router.get("/patients/{patient_id}/notes")
async def list_notes(patient_id: str):
    rows = await db.list_notes(patient_id)
    return {"notes": rows}


# ── Tasks ─────────────────────────────────────────────────────────────────────

@router.post("/patients/{patient_id}/tasks", status_code=201)
async def add_task(patient_id: str, body: TaskCreate):
    return await db.add_task(patient_id, body.model_dump(exclude_none=True))


@router.patch("/patients/{patient_id}/tasks/{task_id}")
async def toggle_task(patient_id: str, task_id: str, body: TaskToggle):
    return await db.toggle_task(task_id, body.done)


# ── Training / feedback ───────────────────────────────────────────────────────

@router.post("/training/outcome", status_code=201)
async def log_outcome(body: TrainingOutcome):
    """
    Log a real SHA adjudication outcome against a pipeline run.
    Updates tariff_confidence_matrix automatically.
    Used for agent calibration and eventual fine-tuning dataset.
    """
    result = await db.log_training_outcome(body.model_dump(exclude_none=True))
    return {"status": "logged", "id": result.get("id") if isinstance(result, dict) else None}


@router.get("/training/outcomes")
async def list_outcomes(
    facility_id: str = Query(default=FACILITY_ID),
    limit: int = Query(default=50, le=500),
):
    """List logged training outcomes — use to review agent prediction accuracy."""
    try:
        from app.ehr.db import _get
        rows = await _get("/training_outcomes", {
            "facility_id": f"eq.{facility_id}",
            "order": "created_at.desc",
            "limit": str(limit),
        })
        return {"outcomes": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── FHIR R4 ingestion + Fable 5 claim construction ────────────────────────────

@router.post("/fhir/claim")
async def fhir_to_claim(body: dict):
    """
    Accept an HL7 FHIR R4 Bundle and use Fable 5 to construct a SHA ClaimRequest.
    Returns a draft for human review — does NOT auto-submit to the pipeline.

    Body: { "bundle": {...FHIR R4 Bundle...}, "facility_id": "DHABP00301" }
    Response: { claim_request, confidence, missing_fields, extraction_notes, ready_for_review }
    """
    from app.sha_claims.claim_builder import build_claim_from_fhir

    bundle = body.get("bundle")
    if not bundle or not isinstance(bundle, dict):
        raise HTTPException(status_code=422, detail="Body must contain a 'bundle' key with a FHIR R4 Bundle object.")

    facility_id = body.get("facility_id") or FACILITY_ID
    try:
        result = await build_claim_from_fhir(bundle, facility_id)
        return result
    except Exception as e:
        logger.error(f"FHIR claim build error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context/claim")
async def context_to_claim(body: dict):
    """
    Accept free-text clinical context (encounter notes, discharge summary, etc.)
    and use Fable 5 to extract a SHA ClaimRequest draft for human review.

    Body: { "text": "Patient James Ochieng...", "facility_id": "DHABP00301" }
    Response: { claim_request, confidence, missing_fields, extraction_notes, ready_for_review }
    """
    from app.sha_claims.claim_builder import build_claim_from_context

    text = body.get("text") or ""
    if not text.strip():
        raise HTTPException(status_code=422, detail="Body must contain a non-empty 'text' field.")

    if len(text) > 12000:
        text = text[:12000]  # Fable 5 context cap for this use case

    facility_id = body.get("facility_id") or FACILITY_ID
    try:
        result = await build_claim_from_context(text, facility_id)
        return result
    except Exception as e:
        logger.error(f"Context claim build error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/training/accuracy")
async def training_accuracy(facility_id: str = Query(default=FACILITY_ID)):
    """
    Compare FADCPE predictions vs actual outcomes.
    Returns calibration metrics: how accurate was each agent?
    """
    try:
        from app.ehr.db import _get
        rows = await _get("/training_outcomes", {
            "facility_id": f"eq.{facility_id}",
            "select": "actual_outcome,fadcpe_predicted_risk,fadcpe_predicted_score,ri_predicted_rate,actual_payment_kes,days_to_payment",
        })

        if not rows:
            return {"message": "No outcomes logged yet.", "n": 0}

        n = len(rows)
        approved = sum(1 for r in rows if r.get("actual_outcome") == "approved")
        rejected = sum(1 for r in rows if r.get("actual_outcome") == "rejected")

        # FADCPE calibration: did high-risk calls actually reject?
        high_risk = [r for r in rows if r.get("fadcpe_predicted_risk") in ("high", "critical")]
        high_risk_rejected = sum(1 for r in high_risk if r.get("actual_outcome") == "rejected")

        low_risk = [r for r in rows if r.get("fadcpe_predicted_risk") == "low"]
        low_risk_approved = sum(1 for r in low_risk if r.get("actual_outcome") == "approved")

        ri_errors = []
        for r in rows:
            pred = r.get("ri_predicted_rate")
            if pred is not None and r.get("actual_outcome") is not None:
                actual = 1.0 if r["actual_outcome"] == "approved" else 0.0
                ri_errors.append(abs(float(pred) - actual))

        return {
            "n": n,
            "approved": approved,
            "rejected": rejected,
            "approval_rate_actual": round(approved / n, 3),
            "fadcpe_high_risk_precision": round(high_risk_rejected / len(high_risk), 3) if high_risk else None,
            "fadcpe_low_risk_recall": round(low_risk_approved / len(low_risk), 3) if low_risk else None,
            "ri_mean_absolute_error": round(sum(ri_errors) / len(ri_errors), 3) if ri_errors else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
