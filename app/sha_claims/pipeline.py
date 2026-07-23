"""
SHA Claims Pipeline — orchestrates EBV → PAA → CCE → FADCPE → RI → Submit.
Yields Server-Sent Events for real-time frontend updates.
"""

import json
import logging
import time
import uuid
from datetime import date
from typing import AsyncIterator

from app.sha_claims.agents.cce import CCEAgent
from app.sha_claims.agents.ebv import EBVAgent
from app.sha_claims.agents.fadcpe import FADCPEAgent
from app.sha_claims.agents.paa import PAAAgent
from app.sha_claims.agents.ri import RIAgent
from app.sha_claims.events import log_event, upsert_claim
from app.sha_claims.models import ClaimRequest, PipelineResult
from app.sha_claims.sha_client import sha_client

logger = logging.getLogger(__name__)

_ebv_agent = EBVAgent()
_paa_agent = PAAAgent()
_cce_agent = CCEAgent()
_fadcpe_agent = FADCPEAgent()
_ri_agent = RIAgent()


def _sse(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, **data})}\n\n"


async def run_pipeline(req: ClaimRequest) -> AsyncIterator[str]:
    """Run the full 5-agent claims pipeline, yielding SSE events."""
    claim_id = f"CLM-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    facility_id = req.facility_id
    t_start = time.monotonic()
    result = PipelineResult(claim_id=claim_id, facility_id=facility_id, status="running")

    await log_event(claim_id, facility_id, "CLAIM_INITIATED", {
        "patient_name": req.patient.name,
        "id_number": req.patient.id_number,
        "scheme": req.patient.scheme,
        "encounter_type": req.encounter_type,
        "service_date": str(req.service_date),
        "n_line_items": len(req.line_items),
    })

    yield _sse("PIPELINE_STARTED", {"claim_id": claim_id, "facility_id": facility_id})

    # ── Agent 1: EBV ──────────────────────────────────────────────────────
    yield _sse("EBV_STARTED", {"claim_id": claim_id})
    await log_event(claim_id, facility_id, "EBV_STARTED", {})
    try:
        ebv = await _ebv_agent.run(req)
        result.ebv = ebv
        await log_event(claim_id, facility_id, "EBV_COMPLETED", ebv.model_dump(),
                        sha_data=ebv.raw_sha_response)
        yield _sse("EBV_COMPLETED", {
            "claim_id": claim_id,
            "eligible": ebv.eligible,
            "scheme": ebv.scheme,
            "error": ebv.error,
            "confidence": ebv.confidence,
        })
        if not ebv.eligible and not ebv.error:
            result.status = "blocked_ineligible"
            yield _sse("PIPELINE_BLOCKED", {
                "claim_id": claim_id,
                "reason": "Member not eligible for SHA coverage on this date.",
            })
            await _finalize(result, t_start)
            return
    except Exception as e:
        logger.error(f"EBV failed: {e}")
        yield _sse("AGENT_ERROR", {"claim_id": claim_id, "agent": "EBV", "error": str(e)})
        result.status = "error"
        result.error = str(e)
        await _finalize(result, t_start)
        return

    # ── Agent 2: PAA ──────────────────────────────────────────────────────
    paa = None  # keep in scope for later agents
    yield _sse("PAA_STARTED", {"claim_id": claim_id})
    await log_event(claim_id, facility_id, "PAA_STARTED", {})
    try:
        paa = await _paa_agent.run(req, ebv)
        result.paa = paa
        await log_event(claim_id, facility_id, "PAA_COMPLETED", paa.model_dump())
        yield _sse("PAA_COMPLETED", {
            "claim_id": claim_id,
            "pre_auth_required": paa.pre_auth_required,
            "risk_level": paa.risk_level,
            "recommendation": paa.recommendation[:200],
            "confidence": paa.confidence,
        })
    except Exception as e:
        logger.error(f"PAA failed: {e}")
        yield _sse("AGENT_ERROR", {"claim_id": claim_id, "agent": "PAA", "error": str(e)})

    # ── Agent 3: CCE ──────────────────────────────────────────────────────
    yield _sse("CCE_STARTED", {"claim_id": claim_id})
    await log_event(claim_id, facility_id, "CCE_STARTED", {})
    try:
        cce = await _cce_agent.run(req, claim_id)
        result.cce = cce
        await log_event(claim_id, facility_id, "CCE_COMPLETED", {
            "n_items": len(cce.mapped_items),
            "total_amount": cce.total_claim_amount,
            "coding_notes": cce.coding_notes[:300],
        })
        yield _sse("CCE_COMPLETED", {
            "claim_id": claim_id,
            "n_mapped_items": len(cce.mapped_items),
            "total_claim_amount": cce.total_claim_amount,
            "items": [i.model_dump() for i in cce.mapped_items],
            "confidence": cce.confidence,
        })
    except Exception as e:
        logger.error(f"CCE failed: {e}")
        yield _sse("AGENT_ERROR", {"claim_id": claim_id, "agent": "CCE", "error": str(e)})
        result.status = "error"
        result.error = str(e)
        await _finalize(result, t_start)
        return

    # ── Agent 4: FADCPE ───────────────────────────────────────────────────
    fadcpe = None  # keep in scope for RI
    yield _sse("FADCPE_STARTED", {"claim_id": claim_id})
    await log_event(claim_id, facility_id, "FADCPE_STARTED", {})
    try:
        from app.sha_claims.models import PAAResult as _PAAResult
        _paa_for_fadcpe = (
            result.paa or paa
            or _PAAResult(pre_auth_required=False, risk_level="low", recommendation="", reasoning="")
        )
        fadcpe = await _fadcpe_agent.run(req, ebv, _paa_for_fadcpe, cce)
        result.fadcpe = fadcpe
        await log_event(claim_id, facility_id, "FADCPE_COMPLETED", fadcpe.model_dump(),
                        agent_predictions=fadcpe.per_code_scores)
        yield _sse("FADCPE_COMPLETED", {
            "claim_id": claim_id,
            "overall_risk": fadcpe.overall_risk,
            "risk_score": fadcpe.risk_score,
            "flagged_codes": fadcpe.flagged_codes,
            "recommendations": fadcpe.recommendations,
            "confidence": fadcpe.confidence,
        })
    except Exception as e:
        logger.error(f"FADCPE failed: {e}")
        yield _sse("AGENT_ERROR", {"claim_id": claim_id, "agent": "FADCPE", "error": str(e)})

    # ── Agent 5: RI ───────────────────────────────────────────────────────
    yield _sse("RI_STARTED", {"claim_id": claim_id})
    await log_event(claim_id, facility_id, "RI_STARTED", {})
    try:
        from app.sha_claims.models import FADCPEResult, PAAResult
        _paa_safe = result.paa or paa or PAAResult(pre_auth_required=False, risk_level="low", recommendation="", reasoning="")
        _fadcpe_safe = result.fadcpe or fadcpe or FADCPEResult(overall_risk="low", risk_score=0.1, per_code_scores={}, flagged_codes=[], recommendations=[])
        ri = await _ri_agent.run(req, ebv, _paa_safe, cce, _fadcpe_safe)
        result.ri = ri
        await log_event(claim_id, facility_id, "RI_COMPLETED", ri.model_dump())
        yield _sse("RI_COMPLETED", {
            "claim_id": claim_id,
            "expected_approval_rate": ri.expected_approval_rate,
            "expected_payment_amount": ri.expected_payment_amount,
            "expected_days_to_payment": ri.expected_days_to_payment,
            "tips": ri.revenue_optimization_tips,
            "appeal_strategy": ri.appeal_strategy,
            "confidence": ri.confidence,
        })
    except Exception as e:
        logger.error(f"RI failed: {e}")
        yield _sse("AGENT_ERROR", {"claim_id": claim_id, "agent": "RI", "error": str(e)})

    # ── Submit to SHA ─────────────────────────────────────────────────────
    if result.cce and result.cce.sha_claim_payload:
        yield _sse("SUBMISSION_STARTED", {"claim_id": claim_id})
        await log_event(claim_id, facility_id, "CLAIM_SUBMITTED",
                        result.cce.sha_claim_payload)
        sha_resp = await sha_client.submit_claim(result.cce.sha_claim_payload)

        sha_status = "submitted"
        sha_ref = None
        rejection_code = None
        rejection_reason = None

        if sha_resp["status_code"] in (200, 201, 202):
            data = sha_resp["data"] or {}
            sha_ref = data.get("claimRef") or data.get("ref") or data.get("id")
            sha_status = data.get("status", "submitted")
            if sha_status == "approved":
                await log_event(claim_id, facility_id, "CLAIM_APPROVED",
                                {"sha_ref": sha_ref, "amount": cce.total_claim_amount},
                                sha_data=data)
            elif sha_status == "rejected":
                rejection_code = data.get("rejectionCode")
                rejection_reason = data.get("rejectionReason")
                await log_event(claim_id, facility_id, "CLAIM_REJECTED",
                                {"sha_ref": sha_ref, "code": rejection_code},
                                sha_data=data)
        else:
            # SHA UAT unreachable or returned an error (no credentials, 522, etc.)
            # The 5-agent pipeline ran successfully — claim is coded and ready.
            # Mark as "queued" for manual or batch resubmission, not "error".
            sha_status = "queued"
            rejection_reason = sha_resp.get("error")
            await log_event(claim_id, facility_id, "SHA_SUBMISSION_DEFERRED", {
                "status_code": sha_resp["status_code"],
                "error": sha_resp.get("error"),
                "note": "SHA UAT unreachable. Claim fully coded — queued for resubmission.",
            })

        from app.sha_claims.models import ClaimSubmissionResult
        submission = ClaimSubmissionResult(
            sha_ref=sha_ref,
            status=sha_status,
            rejection_code=rejection_code,
            rejection_reason=rejection_reason,
            raw_response=sha_resp.get("data"),
        )
        result.submission = submission
        result.status = sha_status

        rejection_detail = None
        if rejection_code:
            try:
                from app.sha_claims.rejection_codes import get_rejection_info
                info = get_rejection_info(rejection_code)
                if info:
                    rejection_detail = {
                        "description": info["description"],
                        "fix_action": info["fix_action"],
                        "appealable": info["appealable"],
                        "appeal_window_days": info["appeal_window_days"],
                    }
            except ImportError:
                pass

        yield _sse("SUBMISSION_COMPLETE", {
            "claim_id": claim_id,
            "sha_ref": sha_ref,
            "status": sha_status,
            "rejection_code": rejection_code,
            "rejection_reason": rejection_reason,
            "rejection_detail": rejection_detail,
        })
    else:
        result.status = "pipeline_complete_no_submit"

    await _finalize(result, t_start)
    yield _sse("PIPELINE_COMPLETE", {
        "claim_id": claim_id,
        "status": result.status,
        "total_duration_ms": result.total_duration_ms,
        "summary": {
            "eligible": result.ebv.eligible if result.ebv else None,
            "risk": result.fadcpe.overall_risk if result.fadcpe else None,
            "claim_amount": result.cce.total_claim_amount if result.cce else None,
            "expected_payment": result.ri.expected_payment_amount if result.ri else None,
            "sha_ref": result.submission.sha_ref if result.submission else None,
        },
    })


async def _finalize(result: PipelineResult, t_start: float) -> None:
    result.total_duration_ms = int((time.monotonic() - t_start) * 1000)

    def _safe(v):
        if v is None:
            return None
        if hasattr(v, "model_dump"):
            return v.model_dump()
        return v

    await upsert_claim({
        "claim_id": result.claim_id,
        "facility_id": result.facility_id,
        "status": result.status,
        "ebv_result": _safe(result.ebv),
        "paa_result": _safe(result.paa),
        "cce_result": _safe(result.cce),
        "fadcpe_result": _safe(result.fadcpe),
        "ri_result": _safe(result.ri),
        "sha_payload": result.cce.sha_claim_payload if result.cce else None,
        "sha_response": result.submission.raw_response if result.submission else None,
        "sha_ref": result.submission.sha_ref if result.submission else None,
        "claim_amount": result.cce.total_claim_amount if result.cce else None,
        "scheme": result.cce.sha_claim_payload.get("schemeCode") if result.cce else None,
        "encounter_type": result.cce.sha_claim_payload.get("encounterType") if result.cce else None,
        "service_date": str(result.cce.sha_claim_payload.get("serviceDate")) if result.cce else None,
        "icd_codes": [i.icd_code for i in result.cce.mapped_items] if result.cce else [],
        "tariff_codes": [i.sha_tariff_code for i in result.cce.mapped_items] if result.cce else [],
        "pipeline_status": {
            "ebv": "done" if result.ebv else "skipped",
            "paa": "done" if result.paa else "skipped",
            "cce": "done" if result.cce else "skipped",
            "fadcpe": "done" if result.fadcpe else "skipped",
            "ri": "done" if result.ri else "skipped",
        },
    })
