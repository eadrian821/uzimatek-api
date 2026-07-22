"""
PAA — Pre-Authorization Assessment Agent (Fable 5)
Determines whether the encounter requires SHA pre-authorization and risk-levels it.
"""

import logging

from app.agents.base import BaseAgent, AgentResponse
from app.sha_claims.models import ClaimRequest, EBVResult, PAAResult

logger = logging.getLogger(__name__)

# SHA services that always require pre-auth under SHIF
_PREAUTH_REQUIRED_ENCOUNTERS = {"inpatient", "surgery", "maternity"}
_PREAUTH_PROCEDURES = {
    "surgery", "dialysis", "chemotherapy", "radiotherapy",
    "MRI", "CT scan", "endoscopy", "colonoscopy", "cardiac catheterization",
}


class PAAAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="PAA",
            description="Pre-Authorization Assessment — flags claims requiring SHA pre-auth and risk-levels the encounter.",
        )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a SHA Kenya (Social Health Authority) pre-authorization specialist at MTRH Eldoret. "
            "Apply SHA's actual pre-authorization rules:\n"
            "- SHIF inpatient admissions >24h: pre-auth REQUIRED within 24h of admission.\n"
            "- Elective surgery, oncology, dialysis, MRI/CT, cardiac procedures: pre-auth REQUIRED.\n"
            "- Linda Mama: all maternity services covered without pre-auth for enrolled members.\n"
            "- CSPS: broader coverage, but surgical and specialist referrals need pre-auth.\n"
            "- Emergency presentations: pre-auth waived for first 24h, then required for continued admission.\n"
            "Missed pre-auth triggers E007 rejection — the most common appeal-ineligible error. "
            "Your assessment is structured: YES/NO on pre-auth, LOW/MEDIUM/HIGH risk, and a concrete action list. "
            "Be direct — the claims clerk acts on your output immediately."
        )

    @property
    def capabilities(self) -> list:
        return ["pre_auth_assessment", "encounter_risk_scoring", "documentation_checklist"]

    async def process(self, message, intent, context, attachments=None) -> AgentResponse:
        return AgentResponse(agent=self.name, content="Use run() for SHA pipeline.", confidence=0.0)

    async def run(self, req: ClaimRequest, ebv: EBVResult) -> PAAResult:
        encounter_lower = req.encounter_type.lower()
        rule_based_preauth = encounter_lower in _PREAUTH_REQUIRED_ENCOUNTERS

        diagnosis_lower = req.diagnosis.lower()
        flagged_by_rules = [p for p in _PREAUTH_PROCEDURES if p.lower() in diagnosis_lower]

        prompt = (
            f"Encounter: {req.encounter_type}\n"
            f"Scheme: {req.patient.scheme}\n"
            f"Presenting complaint: {req.presenting_complaint}\n"
            f"Diagnosis: {req.diagnosis}\n"
            f"Clinical notes: {req.clinical_notes or 'None'}\n"
            f"Service date: {req.service_date}\n"
            f"Eligibility confirmed: {ebv.eligible}\n"
            f"Rule-based pre-auth required: {rule_based_preauth}\n\n"
            "Assess:\n"
            "1. Is SHA pre-authorization required? (YES/NO and why)\n"
            "2. Risk level: LOW / MEDIUM / HIGH\n"
            "3. Any specific documentation requirements or flags\n"
            "4. Recommendation for the claims clerk\n"
            "Be concise and actionable."
        )

        analysis = await self._call_claude(
            messages=[{"role": "user", "content": prompt}],
            use_fable_model=True,
            max_tokens=2000,
            thinking_budget=1200,
        )

        pre_auth = rule_based_preauth or bool(flagged_by_rules) or "YES" in analysis.upper()[:100]

        if "HIGH" in analysis.upper():
            risk = "high"
        elif "MEDIUM" in analysis.upper():
            risk = "medium"
        else:
            risk = "low"

        return PAAResult(
            pre_auth_required=pre_auth,
            risk_level=risk,
            recommendation=analysis[:300],
            reasoning=analysis,
            flagged_items=flagged_by_rules,
            confidence=0.92,
        )
