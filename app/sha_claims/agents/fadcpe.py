"""
FADCPE — Fraud / Anomaly Detection & Per-Code Error Prediction
Scores the claim against each SHA rejection code (E001–E010).
"""

import logging
from typing import Any, Dict, List

from app.agents.base import BaseAgent, AgentResponse
from app.sha_claims.models import CCEResult, ClaimRequest, EBVResult, FADCPEResult, PAAResult

logger = logging.getLogger(__name__)

# Rejection code definitions
REJECTION_CODES: Dict[str, str] = {
    "E001": "Member not found in SHA database",
    "E002": "Member not covered on date of service",
    "E003": "Service/tariff not covered under scheme (appealable)",
    "E004": "Insufficient supporting documentation (appealable)",
    "E005": "Duplicate claim — same member, date, facility, service",
    "E006": "Tariff code mismatch / incorrect coding (appealable)",
    "E007": "Pre-authorization required but not obtained",
    "E008": "Claim submitted outside the 90-day window",
    "E009": "Facility not accredited for this service level",
    "E010": "Benefit limit exceeded",
}

APPEALABLE = {"E003", "E004", "E006"}


class FADCPEAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="FADCPE",
            description="Fraud/Anomaly Detection & Per-Code Error Prediction — scores claim against each SHA rejection code.",
        )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a SHA Kenya claims auditor and fraud/error detection specialist. "
            "You understand the SHA adjudication engine's logic and how each rejection code is triggered:\n"
            "  E001: member ID not in NHIF/SHA registry\n"
            "  E002: coverage lapsed before service date\n"
            "  E003: service not in scheme benefit package (appealable)\n"
            "  E004: missing documents — clinical notes, lab results, referral (appealable)\n"
            "  E005: exact duplicate within 30-day window\n"
            "  E006: tariff code does not match ICD-10 in SHA schedule (appealable)\n"
            "  E007: pre-authorization required but reference number absent\n"
            "  E008: claim submitted >90 days from service date\n"
            "  E009: facility's accreditation level does not cover this service\n"
            "  E010: annual benefit cap reached for this member/scheme\n\n"
            "Output ONLY valid JSON: {\"E001\": 0.0, ..., \"E010\": 0.0}. "
            "Each score is a probability 0.0–1.0. Be calibrated — a score above 0.5 should mean you "
            "genuinely believe that code will trigger. Do not flag everything; that destroys signal."
        )

    @property
    def capabilities(self) -> list:
        return ["rejection_risk_scoring", "per_code_prediction", "fraud_flag"]

    async def process(self, message, intent, context, attachments=None) -> AgentResponse:
        return AgentResponse(agent=self.name, content="Use run() for SHA pipeline.", confidence=0.0)

    async def run(
        self,
        req: ClaimRequest,
        ebv: EBVResult,
        paa: PAAResult,
        cce: CCEResult,
    ) -> FADCPEResult:
        rule_scores = self._rule_based_scores(req, ebv, paa, cce)
        claude_scores = await self._claude_scores(req, ebv, paa, cce, rule_scores)
        merged = self._merge(rule_scores, claude_scores)

        flagged = [code for code, score in merged.items() if score >= 0.4]
        overall_score = max(merged.values()) if merged else 0.0

        if overall_score >= 0.7:
            overall_risk = "critical"
        elif overall_score >= 0.4:
            overall_risk = "high"
        elif overall_score >= 0.2:
            overall_risk = "medium"
        else:
            overall_risk = "low"

        recommendations = self._recommendations(req, flagged, paa, cce)

        return FADCPEResult(
            overall_risk=overall_risk,
            risk_score=round(overall_score, 3),
            per_code_scores={k: round(v, 3) for k, v in merged.items()},
            flagged_codes=flagged,
            recommendations=recommendations,
            confidence=0.88,
        )

    def _rule_based_scores(
        self, req: ClaimRequest, ebv: EBVResult, paa: PAAResult, cce: CCEResult
    ) -> Dict[str, float]:
        scores: Dict[str, float] = {k: 0.0 for k in REJECTION_CODES}

        # E001 — member not found
        if not ebv.eligible or ebv.member_id is None:
            scores["E001"] = 0.8
        elif ebv.error:
            scores["E001"] = 0.4  # UAT was down, can't confirm

        # E002 — not covered on date
        if not ebv.eligible:
            scores["E002"] = 0.7

        # E003 — service not covered
        # Linda Mama covers maternity; SHIF covers general; CSPS is comprehensive
        if req.patient.scheme == "LINDA_MAMA" and req.encounter_type not in ("maternity", "outpatient"):
            scores["E003"] = 0.6
        for item in cce.mapped_items:
            if item.mapping_confidence < 0.7:
                scores["E003"] = max(scores["E003"], 0.35)

        # E004 — insufficient docs
        if paa.risk_level == "high":
            scores["E004"] = 0.5
        if req.clinical_notes is None or len(req.clinical_notes or "") < 20:
            scores["E004"] = max(scores["E004"], 0.3)

        # E006 — tariff mismatch
        low_conf_items = [i for i in cce.mapped_items if i.mapping_confidence < 0.75]
        if low_conf_items:
            scores["E006"] = min(0.3 + 0.1 * len(low_conf_items), 0.7)
        for item in cce.mapped_items:
            if item.historical_approval_rate is not None and item.historical_approval_rate < 0.6:
                scores["E006"] = max(scores["E006"], 0.5)

        # E007 — pre-auth required
        if paa.pre_auth_required:
            scores["E007"] = 0.85

        # E009 — facility accreditation
        # Can't check without registry; assign low baseline
        scores["E009"] = 0.05

        # E010 — benefit limit
        limits = ebv.benefit_limits or {}
        limit_key = req.encounter_type
        if limit_key in limits:
            limit = float(limits[limit_key])
            if cce.total_claim_amount > limit * 0.9:
                scores["E010"] = 0.7
            elif cce.total_claim_amount > limit * 0.7:
                scores["E010"] = 0.3

        return scores

    async def _claude_scores(
        self,
        req: ClaimRequest,
        ebv: EBVResult,
        paa: PAAResult,
        cce: CCEResult,
        rule_scores: Dict[str, float],
    ) -> Dict[str, float]:
        prompt = (
            f"SHA claim risk assessment:\n"
            f"Facility: {req.facility_id} | Scheme: {req.patient.scheme} | Encounter: {req.encounter_type}\n"
            f"Diagnosis: {req.diagnosis}\n"
            f"Total claim: KES {cce.total_claim_amount:,.0f}\n"
            f"Eligibility: {'Confirmed' if ebv.eligible else 'NOT CONFIRMED'}"
            + (f" (error: {ebv.error})" if ebv.error else "") + "\n"
            f"Pre-auth required: {paa.pre_auth_required} | Risk: {paa.risk_level}\n"
            f"CCE confidence: {cce.confidence}\n"
            f"Mapped items: {len(cce.mapped_items)} line(s), min confidence: "
            f"{min((i.mapping_confidence for i in cce.mapped_items), default=0):.2f}\n"
            f"Rule-based scores: {rule_scores}\n\n"
            "Adjust the rejection probability scores (0.0–1.0) for each code E001–E010 "
            "based on the clinical context. Respond ONLY as JSON:\n"
            '{"E001": 0.1, "E002": 0.05, "E003": 0.2, ...}'
        )
        try:
            raw = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                use_fable_model=True,
                max_tokens=1500,
                thinking_budget=800,
            )
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                import json
                return json.loads(raw[start:end])
        except Exception as e:
            logger.warning(f"FADCPE Claude scoring failed: {e}")
        return {}

    def _merge(self, rule: Dict[str, float], claude: Dict[str, float]) -> Dict[str, float]:
        merged: Dict[str, float] = {}
        for code in REJECTION_CODES:
            r = rule.get(code, 0.0)
            c = float(claude.get(code, 0.0)) if code in claude else None
            if c is not None:
                # Weighted blend: 40% rules, 60% Claude
                merged[code] = 0.4 * r + 0.6 * c
            else:
                merged[code] = r
        return merged

    def _recommendations(
        self,
        req: ClaimRequest,
        flagged: List[str],
        paa: PAAResult,
        cce: CCEResult,
    ) -> List[str]:
        recs: List[str] = []
        for code in flagged:
            if code == "E001":
                recs.append("Verify member ID number in SHA member portal before submission.")
            elif code == "E002":
                recs.append("Confirm scheme coverage dates match the service date.")
            elif code == "E003":
                recs.append("Check if service is included in the scheme benefit package; consider appeal if rejected.")
            elif code == "E004":
                recs.append("Attach clinical notes, investigation results, and referral letters.")
            elif code == "E006":
                recs.append("Review tariff code selection — consider querying SHA tariff helpdesk.")
            elif code == "E007":
                recs.append("Obtain pre-authorization from SHA before service delivery where required.")
            elif code == "E010":
                recs.append("Check remaining benefit balance; consider patient top-up payment for excess.")
        if not recs:
            recs.append("Claim appears low-risk. Proceed to submission.")
        return recs
