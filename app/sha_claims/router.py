"""FastAPI router for SHA claims pipeline — /api/sha/*"""

import base64
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.sha_claims.agents.cce import SHA_TARIFF
from app.sha_claims.document import generate_claim_pdf, generate_qr_bytes
from app.sha_claims.events import (
    get_claim_by_id,
    get_claims_list,
    get_facility_stats,
    get_tariff_confidence,
)
from app.sha_claims.models import ClaimRequest
from app.sha_claims.pipeline import run_pipeline
from app.sha_claims.rejection_codes import (
    build_appeal_template,
    get_all_codes_summary,
    get_rejection_info,
)
from app.sha_claims.sha_client import sha_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sha", tags=["SHA Claims"])


# ── Pipeline ──────────────────────────────────────────────────────────────────

@router.post("/claims")
async def submit_claim(req: ClaimRequest):
    """
    Run the full SHA claims pipeline (EBV → PAA → CCE → FADCPE → RI → Submit).
    Returns a Server-Sent Events stream with real-time agent updates.
    """
    return StreamingResponse(
        run_pipeline(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ── Claims list / stats — must be defined BEFORE /{claim_id} routes ──────────

@router.get("/claims/stats")
async def claim_stats(facility_id: str = Query(default="DHABP00301")):
    """Claim statistics for dashboard KPIs."""
    stats = await get_facility_stats(facility_id)
    return {"facility_id": facility_id, **stats}


@router.get("/claims")
async def list_claims(
    facility_id: str = Query(default="DHABP00301"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List recent claims for a facility, including sha_payload for patient name display."""
    claims = await get_claims_list(facility_id, limit)
    return {"facility_id": facility_id, "claims": claims, "count": len(claims)}


# ── Single claim detail + sub-resources ──────────────────────────────────────

@router.get("/claims/{claim_id}")
async def get_claim(claim_id: str):
    """Full claim record with all agent results (for detail panel)."""
    claim = await get_claim_by_id(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")
    return claim


@router.get("/claims/{claim_id}/pdf")
async def download_claim_pdf(claim_id: str):
    """
    Download SHA claim summary as an A4 PDF.
    Contains: patient info, encounter details, tariff breakdown,
    risk assessment (FADCPE), revenue projection (RI), and embedded QR code.
    """
    claim = await get_claim_by_id(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    pdf_bytes = generate_claim_pdf(claim)
    if pdf_bytes is None:
        raise HTTPException(
            status_code=503,
            detail="PDF generation unavailable. Ensure fpdf2 is installed: pip install fpdf2",
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="claim-{claim_id}.pdf"',
            "Cache-Control": "no-cache",
        },
    )


@router.get("/claims/{claim_id}/qr")
async def get_claim_qr(claim_id: str):
    """
    QR code PNG for patient claim follow-up.
    Encodes the claim lookup URL. Patients can scan at discharge or at the pharmacy.
    Response: JSON with qr_base64 (PNG) + content string (the QR data).
    """
    claim = await get_claim_by_id(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    sha_ref = claim.get("sha_ref")
    qr_bytes = generate_qr_bytes(claim_id, sha_ref)

    if qr_bytes is None:
        raise HTTPException(
            status_code=503,
            detail="QR generation unavailable. Ensure qrcode is installed: pip install 'qrcode[pil]'",
        )

    content = f"https://check.uzimatek.health/c/{claim_id}"
    if sha_ref:
        content += f"\nSHA-REF:{sha_ref}"

    return {
        "claim_id":   claim_id,
        "qr_base64":  base64.b64encode(qr_bytes).decode(),
        "content":    content,
        "sha_ref":    sha_ref,
    }


@router.get("/claims/{claim_id}/receipt")
async def get_claim_receipt(claim_id: str):
    """Machine-readable JSON receipt for patient or referring facility."""
    claim = await get_claim_by_id(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    payload = claim.get("sha_payload") or {}
    patient = payload.get("patient") or {}
    ri      = claim.get("ri_result") or {}

    return {
        "claim_id":       claim_id,
        "sha_ref":        claim.get("sha_ref"),
        "facility_id":    claim.get("facility_id") or "DHABP00301",
        "status":         claim.get("status"),
        "patient_id":     patient.get("idNumber"),
        "patient_name":   patient.get("name"),
        "sha_member_id":  patient.get("memberId"),
        "scheme":         claim.get("scheme"),
        "encounter_type": claim.get("encounter_type"),
        "service_date":   claim.get("service_date"),
        "claim_amount":   claim.get("claim_amount"),
        "expected_payment": ri.get("expected_payment_amount"),
        "days_to_payment":  ri.get("expected_days_to_payment"),
        "created_at":     claim.get("created_at"),
        "qr_lookup":      f"https://check.uzimatek.health/c/{claim_id}",
    }


@router.post("/claims/{claim_id}/outcome")
async def log_claim_outcome(claim_id: str, body: dict):
    """
    Log the real SHA adjudication outcome against a pipeline run.
    Updates tariff_confidence_matrix for agent self-improvement.
    Body mirrors EHR TrainingOutcome model.
    """
    from app.ehr import db as ehr_db
    from app.ehr.models import TrainingOutcome

    claim = await get_claim_by_id(claim_id)

    # Merge claim agent predictions with submitted outcome
    merged = {
        "claim_id":               claim_id,
        "facility_id":            body.get("facility_id") or (claim or {}).get("facility_id") or "DHABP00301",
        "sha_ref":                body.get("sha_ref") or (claim or {}).get("sha_ref"),
        "actual_outcome":         body.get("actual_outcome") or "pending",
        "rejection_code":         body.get("rejection_code"),
        "actual_payment_kes":     body.get("actual_payment_kes"),
        "days_to_payment":        body.get("days_to_payment"),
        "notes":                  body.get("notes"),
        # Pull predictions from stored agent results if not provided
        "fadcpe_predicted_risk":  body.get("fadcpe_predicted_risk") or
                                  ((claim or {}).get("fadcpe_result") or {}).get("overall_risk"),
        "fadcpe_predicted_score": body.get("fadcpe_predicted_score") or
                                  ((claim or {}).get("fadcpe_result") or {}).get("risk_score"),
        "ri_predicted_rate":      body.get("ri_predicted_rate") or
                                  ((claim or {}).get("ri_result") or {}).get("expected_approval_rate"),
        "ri_predicted_days":      body.get("ri_predicted_days") or
                                  ((claim or {}).get("ri_result") or {}).get("expected_days_to_payment"),
        "cce_tariff_codes":       (claim or {}).get("tariff_codes"),
    }

    try:
        outcome = TrainingOutcome(**merged)
        result  = await ehr_db.log_training_outcome(outcome.model_dump(exclude_none=True))
        return {"status": "logged", "claim_id": claim_id, "id": result.get("id") if isinstance(result, dict) else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Dashboard aggregated stats ────────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard_stats(facility_id: str = Query(default="DHABP00301")):
    """
    Aggregated stats for the Dashboard page — one round-trip.
    Returns: claims KPIs + recent claims queue + patient snapshot counts.
    """
    import asyncio
    from app.ehr import db as ehr_db

    stats_task    = get_facility_stats(facility_id)
    claims_task   = get_claims_list(facility_id, limit=6)
    patients_task = ehr_db.list_patients(facility_id)

    stats, recent_claims, patients = await asyncio.gather(
        stats_task, claims_task, patients_task,
        return_exceptions=True,
    )

    if isinstance(stats, Exception):
        stats = {}
    if isinstance(recent_claims, Exception):
        recent_claims = []
    if isinstance(patients, Exception):
        patients = []

    # Clean claims for the queue widget
    queue = []
    for c in (recent_claims or []):
        payload = c.get("sha_payload") or {}
        patient_node = payload.get("patient") if isinstance(payload, dict) else {}
        queue.append({
            "claim_id":    c.get("claim_id"),
            "status":      c.get("status"),
            "scheme":      c.get("scheme"),
            "claim_amount": c.get("claim_amount"),
            "service_date": c.get("service_date"),
            "patient_name": (patient_node or {}).get("name") if isinstance(patient_node, dict) else None,
        })

    # Patient summary for the active-patients widget
    patient_list = [
        {
            "name":    p.get("name"),
            "age":     p.get("age"),
            "sex":     p.get("sex"),
            "risk":    p.get("risk", "low"),
            "ward":    p.get("ward"),
            "bed":     p.get("bed"),
            "problems": [pr.get("name") for pr in (p.get("problems") or [])[:2]],
        }
        for p in (patients or [])[:8]
    ]

    return {
        "facility_id": facility_id,
        "kpis": stats,
        "claims_queue": queue,
        "active_patients": patient_list,
        "total_patients": len(patients or []),
    }


# ── Rejection codes reference ─────────────────────────────────────────────────

@router.get("/rejection-codes")
async def list_rejection_codes():
    """Complete SHA rejection code reference with fix actions and appeal guidance."""
    return {"codes": get_all_codes_summary()}


@router.get("/rejection-codes/{code}")
async def get_rejection_code(code: str):
    """Detailed info for a single SHA rejection code."""
    info = get_rejection_info(code)
    if not info:
        raise HTTPException(status_code=404, detail=f"Unknown rejection code: {code}")
    return info.to_dict()


# ── Appeal generation ─────────────────────────────────────────────────────────

@router.get("/claims/{claim_id}/appeal")
async def get_claim_appeal(claim_id: str, rejection_code: str = Query(...)):
    """
    Generate a SHA appeal letter template for a rejected claim.
    Returns structured appeal data + a printable letter text.

    Requires: ?rejection_code=E006 (or whichever code SHA returned).
    """
    claim = await get_claim_by_id(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    info = get_rejection_info(rejection_code)
    if not info:
        raise HTTPException(status_code=400, detail=f"Unknown rejection code: {rejection_code}")
    if not info.appealable:
        return {
            "claim_id": claim_id,
            "rejection_code": rejection_code,
            "appealable": False,
            "reason": f"{rejection_code} — {info.description} — is not appealable under SHA regulations.",
            "fix_action": info.fix_action,
        }

    payload = claim.get("sha_payload") or {}
    patient = payload.get("patient") if isinstance(payload, dict) else {}

    letter = build_appeal_template(
        code=rejection_code,
        claim_id=claim_id,
        facility_id=claim.get("facility_id") or "DHABP00301",
        patient_name=(patient or {}).get("name") or "Unknown",
        service_date=claim.get("service_date") or "—",
        claim_amount=float(claim.get("claim_amount") or 0),
        sha_ref=claim.get("sha_ref"),
    )

    return {
        "claim_id":            claim_id,
        "rejection_code":      rejection_code,
        "appealable":          True,
        "description":         info.description,
        "fix_action":          info.fix_action,
        "appeal_window_days":  info.appeal_window_days,
        "required_evidence":   info.appeal_evidence,
        "prevention":          info.prevention,
        "letter_template":     letter,
    }


@router.post("/claims/{claim_id}/appeal")
async def submit_claim_appeal(claim_id: str, body: dict):
    """
    Log an appeal submission against a rejected claim.
    Updates claim status to 'appeal' and records appeal notes.
    Body: { rejection_code, appeal_notes, evidence_list }
    """
    from app.sha_claims.events import upsert_claim, log_event

    claim = await get_claim_by_id(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    rejection_code = body.get("rejection_code", "")
    info = get_rejection_info(rejection_code)

    if info and not info.appealable:
        raise HTTPException(
            status_code=400,
            detail=f"{rejection_code} is not appealable. Only E003/E004/E006/E008/E009/E012/E013/E014/E015/E016/E018/E019 can be appealed.",
        )

    # Update claim status to appeal
    await upsert_claim({
        "claim_id": claim_id,
        "facility_id": claim.get("facility_id") or "DHABP00301",
        "status": "appeal",
    })

    await log_event(
        claim_id=claim_id,
        facility_id=claim.get("facility_id") or "DHABP00301",
        event_type="APPEAL_FILED",
        payload={
            "rejection_code": rejection_code,
            "appeal_notes": body.get("appeal_notes"),
            "evidence_list": body.get("evidence_list", []),
        },
    )

    return {
        "status":         "appeal_filed",
        "claim_id":       claim_id,
        "rejection_code": rejection_code,
        "appeal_window":  f"{info.appeal_window_days if info else 30} days" ,
        "next_steps":     info.fix_action if info else "Compile evidence and submit to SHA appeals unit.",
    }


# ── SHA direct endpoints ──────────────────────────────────────────────────────

@router.get("/eligibility/{id_number}")
async def check_eligibility(
    id_number: str,
    scheme: str = Query(default="SHIF"),
):
    """Check SHA member eligibility (live UAT call)."""
    result = await sha_client.check_eligibility(id_number, scheme)
    return {
        "id_number":   id_number,
        "scheme":      scheme,
        "status_code": result["status_code"],
        "eligible":    result["status_code"] == 200 and result["data"] is not None,
        "data":        result["data"],
        "error":       result["error"],
    }


@router.get("/claims/{sha_ref}/status")
async def claim_status(sha_ref: str):
    """Check claim status via SHA UAT."""
    result = await sha_client.get_claim_status(sha_ref)
    return {
        "sha_ref":     sha_ref,
        "status_code": result["status_code"],
        "data":        result["data"],
        "error":       result["error"],
    }


# ── Tariff ────────────────────────────────────────────────────────────────────

@router.get("/tariff/{icd_code}")
async def tariff_lookup(icd_code: str):
    """Look up SHA tariff for an ICD-10 code, including historical approval rate."""
    static     = SHA_TARIFF.get(icd_code)
    historical = await get_tariff_confidence(icd_code)
    if not static and not historical:
        raise HTTPException(status_code=404, detail=f"No tariff data for {icd_code}")
    return {"icd_code": icd_code, "tariff": static, "historical_approval": historical}


@router.get("/tariff")
async def tariff_list(search: Optional[str] = Query(default=None)):
    """List all known SHA tariff codes (optionally filter by ICD prefix or description keyword)."""
    items = [
        {"icd_code": k, **v}
        for k, v in SHA_TARIFF.items()
        if not search or search.lower() in k.lower() or search.lower() in v["desc"].lower()
    ]
    return {"count": len(items), "tariffs": items}


@router.get("/health")
async def sha_health():
    """Check SHA UAT connectivity."""
    result    = await sha_client.check_eligibility("000000000", "SHIF")
    reachable = result["status_code"] not in (0, 522)
    return {
        "sha_uat_reachable": reachable,
        "status_code":       result["status_code"],
        "note":              result["error"] if not reachable else "OK",
    }
