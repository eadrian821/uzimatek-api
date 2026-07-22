"""
EBV — Eligibility & Benefit Verification Agent
Calls SHA UAT to verify member coverage, then uses Haiku to interpret the result.
"""

import logging
from typing import Any, Dict

from app.agents.base import BaseAgent, AgentResponse
from app.sha_claims.models import ClaimRequest, EBVResult
from app.sha_claims.sha_client import sha_client

logger = logging.getLogger(__name__)

_MOCK_ELIGIBLE = {
    "member_id": "SHA-MOCK-001",
    "name": "MEMBER NAME",
    "scheme": "SHIF",
    "coverage_type": "Comprehensive",
    "status": "ACTIVE",
    "benefit_limits": {
        "outpatient": 20000,
        "inpatient": 150000,
        "maternity": 50000,
        "surgery": 200000,
    },
}


class EBVAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="EBV",
            description="Eligibility and Benefit Verification — confirms member SHA coverage before claim construction.",
        )

    @property
    def system_prompt(self) -> str:
        return (
            "You are the SHA eligibility verification specialist for MTRH Eldoret. "
            "You interpret SHA member API responses and produce a structured assessment:\n"
            "- Is the member ELIGIBLE or NOT_ELIGIBLE?\n"
            "- Which scheme: SHIF / Linda Mama / CSPS?\n"
            "- Coverage type and any exclusions relevant to the encounter\n"
            "- Benefit limits for this encounter type (outpatient/inpatient/maternity/surgery)\n"
            "- Any flags that would trigger E001 or E002 rejection\n\n"
            "State ELIGIBLE or NOT_ELIGIBLE on the first line. Be precise — incorrect eligibility "
            "determinations cost the facility the full claim amount."
        )

    @property
    def capabilities(self) -> list:
        return ["sha_eligibility_check", "benefit_interpretation", "coverage_validation"]

    async def process(self, message, intent, context, attachments=None) -> AgentResponse:
        return AgentResponse(agent=self.name, content="Use run() for SHA pipeline.", confidence=0.0)

    async def run(self, req: ClaimRequest) -> EBVResult:
        mock_mode = False
        try:
            from app.core.config import settings
            mock_mode = getattr(settings, "sha_mock_mode", False)
        except Exception:
            pass

        if mock_mode:
            return self._mock_result(req)

        sha_resp = await sha_client.check_eligibility(
            id_number=req.patient.id_number,
            scheme=req.patient.scheme,
        )

        if sha_resp["status_code"] == 522 or sha_resp["error"]:
            logger.warning(f"EBV SHA call failed ({sha_resp['status_code']}): {sha_resp['error']}")
            return self._degraded_result(req, sha_resp)

        return await self._interpret(req, sha_resp)

    async def _interpret(self, req: ClaimRequest, sha_resp: Dict[str, Any]) -> EBVResult:
        data = sha_resp.get("data") or {}
        prompt = (
            f"SHA eligibility response for patient ID {req.patient.id_number} (scheme: {req.patient.scheme}):\n"
            f"{data}\n\n"
            "Determine: Is this member eligible for services on the claim date? "
            "Extract: member_id, scheme, coverage_type, benefit limits for the encounter type. "
            "If any field is missing, state 'not specified'. "
            "Respond in plain text: ELIGIBLE or NOT_ELIGIBLE, then key details."
        )
        analysis = await self._call_claude(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )

        eligible = "NOT_ELIGIBLE" not in analysis.upper()
        return EBVResult(
            eligible=eligible,
            member_id=data.get("member_id") or data.get("memberId"),
            scheme=data.get("scheme") or req.patient.scheme,
            coverage_type=data.get("coverage_type") or data.get("coverageType"),
            benefit_limits=data.get("benefit_limits") or data.get("benefitLimits"),
            raw_sha_response=data,
            confidence=0.95 if eligible else 0.9,
        )

    def _mock_result(self, req: ClaimRequest) -> EBVResult:
        return EBVResult(
            eligible=True,
            member_id=_MOCK_ELIGIBLE["member_id"],
            scheme=req.patient.scheme,
            coverage_type=_MOCK_ELIGIBLE["coverage_type"],
            benefit_limits=_MOCK_ELIGIBLE["benefit_limits"],
            raw_sha_response=_MOCK_ELIGIBLE,
            confidence=1.0,
        )

    def _degraded_result(self, req: ClaimRequest, sha_resp: Dict[str, Any]) -> EBVResult:
        return EBVResult(
            eligible=True,
            scheme=req.patient.scheme,
            error=f"SHA UAT unreachable ({sha_resp['status_code']}): {sha_resp['error']}. Proceeding with assumed eligibility.",
            confidence=0.5,
        )
