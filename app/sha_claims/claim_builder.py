"""
ClaimBuilderAgent — Fable 5

Constructs validated SHA ClaimRequest objects from three input types:
  1. HL7 FHIR R4 Bundle (from KenyaEMR / OpenMRS FHIR2 module)
  2. Free-text clinical context / encounter notes
  3. Structured EHR dict (future use)

Design constraints (per Fable 5 analysis):
  - Never auto-submit — always return ClaimRequest for human review
  - FHIR R4 covers ~80% of Kenya government facilities (KenyaEMR at MTRH)
  - Free-text extraction flags confidence and missing fields
  - Human billing officer must approve before pipeline runs
"""

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, AgentResponse
from app.sha_claims.models import ClaimLineItem, ClaimRequest, PatientInput

logger = logging.getLogger(__name__)

# Compact SHA tariff for Fable 5 context (icd=code/rate)
_SHA_TARIFF_CTX = (
    "I10=SHA-CVD-001/1200|E11.9=SHA-META-001/1500|N18.3=SHA-RENAL-001/2000|"
    "J18.9=SHA-RESP-001/2500|B50=SHA-INF-001/1800|N39.0=SHA-INF-003/1000|"
    "Z00.0=SHA-CONSULT-001/350|O80=SHA-MCH-002/5000|K35.9=SHA-SURG-001/35000|"
    "I50.9=SHA-CVD-002/5000|A09=SHA-GI-001/800|Z34.9=SHA-MCH-001/500|"
    "O82.9=SHA-MCH-003/25000|E03.9=SHA-META-004/1000|B20=SHA-INF-004/2500|"
    "K29.7=SHA-GI-003/1000|F32.9=SHA-MH-001/1500|S06.9=SHA-EMERG-001/10000|"
    "J45.9=SHA-RESP-003/1200|I63.9=SHA-CVD-004/15000|I21.9=SHA-CVD-003/50000|"
    "R50.9=SHA-CONSULT-002/600|M54.5=SHA-MUSC-001/800|L20.9=SHA-DERM-001/700|"
    "T14.9=SHA-EMERG-002/5000|A15=SHA-RESP-006/3000|C50.9=SHA-ONCO-001/15000|"
    "N18.5=SHA-RENAL-002/5000|K92.1=SHA-GI-004/8000|P07=SHA-NEO-001/5000"
)

_FHIR_CLASS_MAP = {
    "AMB": "outpatient", "ambulatory": "outpatient",
    "IMP": "inpatient",  "inpatient encounter": "inpatient",
    "EMER": "emergency", "emergency": "emergency",
    "HH": "outpatient",  "SS": "outpatient",
}

_GENDER_MAP = {"male": "M", "female": "F", "other": "O", "unknown": "O"}

_CLAIM_JSON_SCHEMA = """{
  "patient": {
    "name": "",
    "id_number": "",
    "sha_member_id": null,
    "dob": "YYYY-MM-DD or null",
    "gender": "M",
    "scheme": "SHIF"
  },
  "encounter_type": "outpatient",
  "service_date": "YYYY-MM-DD",
  "presenting_complaint": "",
  "diagnosis": "",
  "clinical_notes": "",
  "line_items": [
    {"icd_code": "", "description": "", "quantity": 1, "unit_cost": 0}
  ],
  "confidence": 0.0,
  "missing_fields": [],
  "extraction_notes": ""
}"""


class ClaimBuilderAgent(BaseAgent):
    """
    Fable 5 agent that constructs SHA ClaimRequests from FHIR bundles or free text.
    Always returns a draft for human review — never submits autonomously.
    """

    def __init__(self) -> None:
        super().__init__(
            name="ClaimBuilder",
            description="Fable 5 claim construction from FHIR bundles or clinical context.",
        )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a senior SHA Kenya medical coder and billing specialist at MTRH Eldoret. "
            "You receive clinical data (FHIR R4 resources or free-text encounter notes) and "
            "construct valid SHA claims. You are an expert in ICD-10-CM, the SHA tariff schedule, "
            "and the SHIF / Linda Mama / CSPS benefit packages.\n\n"
            f"SHA TARIFF (ICD=TariffCode/RateKES): {_SHA_TARIFF_CTX}\n\n"
            "CODING RULES:\n"
            "1. Use specific ICD-10: I10 (not R03.0), E11.9 (not E14) for hypertension/DM.\n"
            "2. Code ALL active conditions that affect management.\n"
            "3. Use SHA tariff rates — not facility charges. If ICD not in list, use Z00.0/350.\n"
            "4. For ambiguous data, choose the most clinically conservative interpretation.\n"
            "5. Flag every missing field you are unsure about in missing_fields[].\n"
            "6. Confidence: 0.9+ if all key fields present; 0.6–0.9 if partial; <0.6 if guessing.\n"
            "7. scheme: SHIF (default), LINDA_MAMA (maternity/OB), CSPS (civil servants).\n\n"
            "Output ONLY the JSON object below. No markdown fences. No surrounding text."
        )

    @property
    def capabilities(self) -> list:
        return ["fhir_ingestion", "context_extraction", "claim_construction", "icd10_mapping"]

    async def process(self, message, intent, context, attachments=None) -> AgentResponse:
        return AgentResponse(agent=self.name, content="Use from_fhir() or from_context().", confidence=0.0)

    # ── Public methods ────────────────────────────────────────────────────────

    async def from_fhir(self, bundle: Dict[str, Any], facility_id: str = "DHABP00301") -> Dict[str, Any]:
        """Parse a FHIR R4 Bundle and construct a ClaimRequest using Fable 5."""
        extracted = self._extract_fhir(bundle)
        prompt = (
            f"FHIR-extracted clinical data:\n{json.dumps(extracted, indent=2, default=str)}\n\n"
            "Construct a complete SHA ClaimRequest from this FHIR data. "
            "Correct ICD-10 codes if needed, map to SHA tariff rates, fill gaps with "
            "clinical reasoning. Respond with the JSON schema only:\n"
            f"{_CLAIM_JSON_SCHEMA}"
        )
        raw = await self._call_claude(
            messages=[{"role": "user", "content": prompt}],
            use_fable_model=True,
            max_tokens=2000,
        )
        return self._parse(raw, facility_id, extracted)

    async def from_context(self, text: str, facility_id: str = "DHABP00301") -> Dict[str, Any]:
        """Extract a ClaimRequest from free-text clinical notes using Fable 5."""
        prompt = (
            f"Clinical encounter notes / context:\n\n{text}\n\n"
            "Extract all SHA claim-relevant information and construct a complete ClaimRequest. "
            "Where data is missing or ambiguous, make the most clinically reasonable assumption "
            "and list the field in missing_fields[]. "
            "Respond with the JSON schema only:\n"
            f"{_CLAIM_JSON_SCHEMA}"
        )
        raw = await self._call_claude(
            messages=[{"role": "user", "content": prompt}],
            use_fable_model=True,
            max_tokens=2000,
        )
        return self._parse(raw, facility_id, {})

    # ── FHIR R4 extractor (deterministic) ────────────────────────────────────

    def _extract_fhir(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        # Support both Bundle and bare resource
        if bundle.get("resourceType") == "Bundle":
            entries = [e.get("resource", {}) for e in bundle.get("entry", [])]
        else:
            entries = [bundle] if bundle.get("resourceType") else []

        by_type: Dict[str, list] = {}
        for r in entries:
            rt = r.get("resourceType")
            if rt:
                by_type.setdefault(rt, []).append(r)

        result: Dict[str, Any] = {}

        # Patient
        pt = (by_type.get("Patient") or [{}])[0]
        if pt:
            names = pt.get("name") or [{}]
            n = names[0]
            given  = " ".join(n.get("given") or [])
            family = n.get("family") or ""
            result["patient_name"] = f"{given} {family}".strip() or None
            result["dob"]    = pt.get("birthDate")
            result["gender"] = _GENDER_MAP.get(pt.get("gender", "").lower(), "M")
            for ident in (pt.get("identifier") or []):
                sys = (ident.get("system") or "").lower()
                val = ident.get("value") or ""
                if any(k in sys for k in ("national", "id-number", "/id")):
                    result["id_number"] = val
                elif any(k in sys for k in ("sha", "nhif", "member")):
                    result["sha_member_id"] = val
            for ext in (pt.get("extension") or []):
                if "scheme" in (ext.get("url") or "").lower():
                    result["scheme"] = ext.get("valueString") or ext.get("valueCode")

        # Encounter
        enc = (by_type.get("Encounter") or [{}])[0]
        if enc:
            cls = enc.get("class") or {}
            code = (cls.get("code") or "").upper()
            result["encounter_type"] = _FHIR_CLASS_MAP.get(code, "outpatient")
            period = enc.get("period") or {}
            result["service_date"] = (period.get("start") or "")[:10] or date.today().isoformat()

        # Conditions (diagnoses)
        diagnoses: List[str] = []
        line_items: List[Dict] = []
        for cond in (by_type.get("Condition") or []):
            coding = ((cond.get("code") or {}).get("coding") or [{}])[0]
            icd     = coding.get("code") or ""
            display = coding.get("display") or (cond.get("code") or {}).get("text") or ""
            if icd:
                diagnoses.append(f"{icd} — {display}")
                line_items.append({
                    "icd_code": icd,
                    "description": display or icd,
                    "quantity": 1,
                    "unit_cost": 0,  # Fable 5 fills SHA rate
                })

        result["diagnoses"] = diagnoses

        # Observations → clinical notes
        obs_notes: List[str] = []
        for obs in (by_type.get("Observation") or []):
            code_obj = obs.get("code") or {}
            name = (code_obj.get("text") or
                    ((code_obj.get("coding") or [{}])[0]).get("display") or "")
            val = obs.get("valueQuantity") or obs.get("valueString") or {}
            if isinstance(val, dict):
                val_str = f"{val.get('value', '')} {val.get('unit', '')}".strip()
            else:
                val_str = str(val) if val else ""
            if name or val_str:
                obs_notes.append(f"{name}: {val_str}".strip(": "))
        if obs_notes:
            result["clinical_notes"] = " | ".join(obs_notes[:15])

        # MedicationRequests as additional line items
        for med in (by_type.get("MedicationRequest") or []):
            mc  = (med.get("medicationCodeableConcept") or {})
            mcd = ((mc.get("coding") or [{}])[0]).get("display") or mc.get("text") or ""
            if mcd:
                line_items.append({"icd_code": "Z00.0", "description": f"Medication: {mcd}", "quantity": 1, "unit_cost": 0})

        # Coverage → scheme
        for cov in (by_type.get("Coverage") or []):
            pt_type = (cov.get("payor") or [{}])[0]
            scheme_name = pt_type.get("display") or ""
            if "linda" in scheme_name.lower():
                result["scheme"] = "LINDA_MAMA"
            elif "csps" in scheme_name.lower() or "civil" in scheme_name.lower():
                result["scheme"] = "CSPS"

        if line_items:
            result["line_items"] = line_items

        return result

    # ── Response parser ────────────────────────────────────────────────────────

    def _parse(
        self,
        raw: str,
        facility_id: str,
        fallback: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                pd   = data.get("patient") or {}
                lis  = data.get("line_items") or []

                line_items = [
                    ClaimLineItem(
                        icd_code    = li.get("icd_code") or "Z00.0",
                        description = li.get("description") or "Service",
                        quantity    = int(li.get("quantity") or 1),
                        unit_cost   = float(li.get("unit_cost") or 350),
                    )
                    for li in lis
                ] or [ClaimLineItem(icd_code="Z00.0", description="Consultation", quantity=1, unit_cost=350)]

                svc_raw = data.get("service_date") or fallback.get("service_date") or ""
                try:
                    svc_date = date.fromisoformat(svc_raw[:10])
                except Exception:
                    svc_date = date.today()

                dob_str = pd.get("dob") or fallback.get("dob")
                try:
                    dob = date.fromisoformat(str(dob_str)[:10]) if dob_str else None
                except Exception:
                    dob = None

                claim_req = ClaimRequest(
                    facility_id         = facility_id,
                    patient             = PatientInput(
                        name          = pd.get("name") or fallback.get("patient_name") or "Unknown",
                        id_number     = pd.get("id_number") or fallback.get("id_number") or "000000000",
                        sha_member_id = pd.get("sha_member_id") or fallback.get("sha_member_id"),
                        dob           = dob,
                        gender        = pd.get("gender") or fallback.get("gender") or "M",
                        scheme        = pd.get("scheme") or fallback.get("scheme") or "SHIF",
                    ),
                    encounter_type      = data.get("encounter_type") or fallback.get("encounter_type") or "outpatient",
                    service_date        = svc_date,
                    presenting_complaint= data.get("presenting_complaint") or "Clinical encounter",
                    diagnosis           = data.get("diagnosis") or ", ".join(fallback.get("diagnoses") or []) or "See notes",
                    clinical_notes      = data.get("clinical_notes") or fallback.get("clinical_notes"),
                    line_items          = line_items,
                )

                return {
                    "claim_request":    claim_req.model_dump(mode="json"),
                    "confidence":       float(data.get("confidence") or 0.7),
                    "missing_fields":   data.get("missing_fields") or [],
                    "extraction_notes": data.get("extraction_notes") or "",
                    "ready_for_review": True,
                }
        except Exception as e:
            logger.error(f"ClaimBuilder parse error: {e!r} | raw[:200]: {raw[:200]}")

        return {
            "claim_request":    None,
            "confidence":       0.0,
            "missing_fields":   ["parse_failed"],
            "extraction_notes": f"Fable 5 response parse error. First 200 chars: {raw[:200]}",
            "ready_for_review": False,
        }


# ── Module-level singletons ───────────────────────────────────────────────────

_builder = ClaimBuilderAgent()


async def build_claim_from_fhir(bundle: Dict[str, Any], facility_id: str = "DHABP00301") -> Dict[str, Any]:
    return await _builder.from_fhir(bundle, facility_id)


async def build_claim_from_context(text: str, facility_id: str = "DHABP00301") -> Dict[str, Any]:
    return await _builder.from_context(text, facility_id)
