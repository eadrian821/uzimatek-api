"""
RI — Revenue Intelligence Agent
Haiku projects expected payment, days to payment, and optimization opportunities.
"""

import logging

from app.agents.base import BaseAgent, AgentResponse
from app.sha_claims.models import (
    CCEResult, ClaimRequest, EBVResult, FADCPEResult, PAAResult, RIResult
)

logger = logging.getLogger(__name__)

# Historical average days to SHA payment by scheme and outcome
_AVG_DAYS: dict = {
    "SHIF":       {"approved": 28, "appeal": 60},
    "LINDA_MAMA": {"approved": 21, "appeal": 45},
    "CSPS":       {"approved": 35, "appeal": 75},
}


class RIAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="RI",
            description="Revenue Intelligence — projects payment probability, cash flow timing, and optimization actions.",
        )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a healthcare revenue cycle manager at MTRH Eldoret, specializing in SHA Kenya reimbursements. "
            "SHA SHIF pays in ~28 days post-approval; Linda Mama in ~21 days; CSPS in ~35 days. "
            "Appeals add 30–45 days. Partial payments happen when line items are partially approved.\n\n"
            "Your output format:\n"
            "1. <XX>% approval probability → KES <amount> expected payment\n"
            "2. ~<N> days to payment (scheme + risk trajectory)\n"
            "3. Three numbered optimization actions the billing team can act on today\n"
            "4. APPEAL STRATEGY: <paragraph> — only if any appealable code (E003/E004/E006) is flagged\n\n"
            "Use exact KES figures. Do not hedge with ranges unless genuinely uncertain. "
            "The CFO reads this to plan the facility's monthly cash position."
        )

    @property
    def capabilities(self) -> list:
        return ["payment_projection", "cash_flow_timing", "appeal_strategy", "revenue_optimization"]

    async def process(self, message, intent, context, attachments=None) -> AgentResponse:
        return AgentResponse(agent=self.name, content="Use run() for SHA pipeline.", confidence=0.0)

    async def run(
        self,
        req: ClaimRequest,
        ebv: EBVResult,
        paa: PAAResult,
        cce: CCEResult,
        fadcpe: FADCPEResult,
    ) -> RIResult:
        scheme = req.patient.scheme
        avg_days = _AVG_DAYS.get(scheme, _AVG_DAYS["SHIF"])
        risk_score = fadcpe.risk_score

        base_approval = max(0.0, 1.0 - risk_score * 1.2)
        base_approval = min(base_approval, 0.98)
        expected_payment = cce.total_claim_amount * base_approval
        days = avg_days["approved"] if risk_score < 0.4 else avg_days["appeal"]

        prompt = (
            f"Claim: KES {cce.total_claim_amount:,.0f} | Scheme: {scheme} | "
            f"Encounter: {req.encounter_type} | Facility: {req.facility_id}\n"
            f"FADCPE risk: {fadcpe.overall_risk} (score {fadcpe.risk_score:.2f})\n"
            f"Flagged rejection codes: {', '.join(fadcpe.flagged_codes) or 'none'}\n"
            f"Eligibility: {'confirmed' if ebv.eligible else 'UNCONFIRMED'}\n"
            f"Pre-auth required: {paa.pre_auth_required}\n"
            f"Coded items: {len(cce.mapped_items)} lines\n"
            f"Model estimates: {base_approval*100:.0f}% approval, KES {expected_payment:,.0f} expected, "
            f"~{days} days to payment\n\n"
            "Provide:\n"
            "1. Refined approval probability (%) and expected KES payment\n"
            "2. Days to payment estimate\n"
            "3. Three specific revenue optimization actions (numbered)\n"
            "4. If risk ≥ medium: one-paragraph appeal strategy (which code is appealable, what evidence needed)\n"
            "Keep it actionable. Use KES amounts."
        )

        analysis = await self._call_claude(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
        )

        tips = self._extract_tips(analysis)
        appeal = self._extract_appeal(analysis, fadcpe)

        return RIResult(
            expected_approval_rate=round(base_approval, 3),
            expected_payment_amount=round(expected_payment, 2),
            expected_days_to_payment=days,
            revenue_optimization_tips=tips,
            appeal_strategy=appeal,
            confidence=0.85,
        )

    def _extract_tips(self, analysis: str) -> list:
        tips = []
        lines = analysis.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped and stripped[0].isdigit() and "." in stripped[:3]:
                tips.append(stripped)
        return tips[:3] if tips else [
            "Ensure all supporting documents are attached before submission.",
            "Submit claim within 90 days of service date.",
            "Follow up with SHA portal 14 days after submission.",
        ]

    def _extract_appeal(self, analysis: str, fadcpe: FADCPEResult) -> str | None:
        from app.sha_claims.agents.fadcpe import APPEALABLE
        has_appealable = bool(set(fadcpe.flagged_codes) & APPEALABLE)
        if not has_appealable and fadcpe.overall_risk in ("low",):
            return None
        lower = analysis.lower()
        idx = lower.find("appeal")
        if idx >= 0:
            return analysis[idx:idx+500].strip()
        return (
            "If claim is rejected, file an appeal within 30 days citing clinical necessity. "
            "Include: clinical notes, lab results, specialist opinion, and tariff justification. "
            f"Appealable codes: {', '.join(set(fadcpe.flagged_codes) & APPEALABLE) or 'none flagged'}."
        )
