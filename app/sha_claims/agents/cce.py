"""
CCE — Clinical Coding Engine (Fable 5)
Maps diagnoses → ICD-10 → SHA tariff codes, constructs the SHA claim payload.
Uses extended thinking to reason about coding ambiguities and tariff specificity.
"""

import json
import logging
from datetime import date
from typing import Any, Dict, List

from app.agents.base import BaseAgent, AgentResponse
from app.sha_claims.events import get_tariff_confidence
from app.sha_claims.models import CCEMappedItem, CCEResult, ClaimRequest, EBVResult

logger = logging.getLogger(__name__)

# SHA Kenya tariff schedule (ICD-10 → SHA tariff)
# Rates in KES as per SHA schedule
SHA_TARIFF: Dict[str, Dict[str, Any]] = {
    "J18.9":  {"code": "SHA-RESP-001", "desc": "Pneumonia/chest infection management",  "rate": 2500},
    "J06.9":  {"code": "SHA-RESP-002", "desc": "Acute upper respiratory infection",       "rate": 800},
    "J45.9":  {"code": "SHA-RESP-003", "desc": "Asthma management",                       "rate": 1200},
    "J22":    {"code": "SHA-RESP-004", "desc": "Lower respiratory infection",              "rate": 1500},
    "J00":    {"code": "SHA-RESP-005", "desc": "Common cold management",                  "rate": 500},
    "I10":    {"code": "SHA-CVD-001",  "desc": "Hypertension management",                 "rate": 1200},
    "I50.9":  {"code": "SHA-CVD-002",  "desc": "Heart failure management",                "rate": 5000},
    "I21.9":  {"code": "SHA-CVD-003",  "desc": "Acute MI management",                     "rate": 50000},
    "I63.9":  {"code": "SHA-CVD-004",  "desc": "Stroke management",                       "rate": 15000},
    "E11.9":  {"code": "SHA-META-001", "desc": "Type 2 diabetes management",              "rate": 1500},
    "E14":    {"code": "SHA-META-002", "desc": "Unspecified diabetes management",         "rate": 1200},
    "E11.65": {"code": "SHA-META-003", "desc": "T2DM with hyperglycaemia",               "rate": 2000},
    "E03.9":  {"code": "SHA-META-004", "desc": "Hypothyroidism management",               "rate": 1000},
    "B50":    {"code": "SHA-INF-001",  "desc": "Falciparum malaria treatment",             "rate": 1800},
    "B54":    {"code": "SHA-INF-002",  "desc": "Unspecified malaria treatment",            "rate": 1500},
    "N39.0":  {"code": "SHA-INF-003",  "desc": "Urinary tract infection management",      "rate": 1000},
    "A09":    {"code": "SHA-GI-001",   "desc": "Diarrhoeal disease management",           "rate": 800},
    "A00.9":  {"code": "SHA-GI-002",   "desc": "Cholera treatment",                       "rate": 3000},
    "B20":    {"code": "SHA-INF-004",  "desc": "HIV disease management",                  "rate": 2500},
    "A15":    {"code": "SHA-RESP-006", "desc": "Tuberculosis treatment",                  "rate": 3000},
    "K29.7":  {"code": "SHA-GI-003",   "desc": "Gastritis management",                   "rate": 1000},
    "K92.1":  {"code": "SHA-GI-004",   "desc": "GI bleed management",                    "rate": 8000},
    "K35.9":  {"code": "SHA-SURG-001", "desc": "Appendectomy",                            "rate": 35000},
    "K80.20": {"code": "SHA-SURG-002", "desc": "Cholecystectomy",                         "rate": 45000},
    "Z34.9":  {"code": "SHA-MCH-001",  "desc": "Antenatal care visit",                    "rate": 500},
    "Z00.1":  {"code": "SHA-MCH-001",  "desc": "Antenatal care visit",                    "rate": 500},
    "O80":    {"code": "SHA-MCH-002",  "desc": "Normal vaginal delivery",                 "rate": 5000},
    "O82.9":  {"code": "SHA-MCH-003",  "desc": "Caesarean section",                       "rate": 25000},
    "O60":    {"code": "SHA-MCH-004",  "desc": "Preterm labour management",               "rate": 8000},
    "P07":    {"code": "SHA-NEO-001",  "desc": "Preterm newborn care (per diem)",         "rate": 5000},
    "N18.3":  {"code": "SHA-RENAL-001","desc": "CKD stage 3 management",                 "rate": 2000},
    "N18.5":  {"code": "SHA-RENAL-002","desc": "CKD stage 5 management",                 "rate": 5000},
    "C50.9":  {"code": "SHA-ONCO-001", "desc": "Breast cancer treatment",                 "rate": 15000},
    "C53":    {"code": "SHA-ONCO-002", "desc": "Cervical cancer treatment",               "rate": 12000},
    "S06.9":  {"code": "SHA-EMERG-001","desc": "Head injury management",                  "rate": 10000},
    "T14.9":  {"code": "SHA-EMERG-002","desc": "Injury/trauma management",               "rate": 5000},
    "F32.9":  {"code": "SHA-MH-001",   "desc": "Depression management",                   "rate": 1500},
    "F20.9":  {"code": "SHA-MH-002",   "desc": "Schizophrenia treatment",                 "rate": 3000},
    "Z12.4":  {"code": "SHA-SCREEN-001","desc": "Cervical cancer screening",              "rate": 400},
    "Z00.0":  {"code": "SHA-CONSULT-001","desc": "General outpatient consultation",       "rate": 350},
    "M54.5":  {"code": "SHA-MUSC-001", "desc": "Lower back pain management",              "rate": 800},
    "L20.9":  {"code": "SHA-DERM-001", "desc": "Atopic dermatitis management",            "rate": 700},
    "H10.9":  {"code": "SHA-OPTH-001", "desc": "Conjunctivitis management",               "rate": 600},
    "G43.9":  {"code": "SHA-NEURO-001","desc": "Migraine management",                     "rate": 1000},
    "R50.9":  {"code": "SHA-CONSULT-002","desc": "Fever NOS — investigation and management","rate": 600},
    "R10.4":  {"code": "SHA-GI-005",   "desc": "Abdominal pain management",               "rate": 700},
    "R05":    {"code": "SHA-RESP-007", "desc": "Cough management",                        "rate": 500},
}

_CONSULT_CODE = {"code": "SHA-CONSULT-001", "desc": "General outpatient consultation", "rate": 350}


class CCEAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="CCE",
            description="Clinical Coding Engine — maps diagnoses to SHA tariff codes and constructs the claim payload.",
        )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a senior medical coder at MTRH Eldoret specializing in SHA Kenya claims. "
            "You are an expert in ICD-10-CM, SHA tariff schedules, and the SHIF/Linda Mama/CSPS benefit packages.\n\n"
            "Coding rules:\n"
            "- Use the most specific ICD-10 code available (e.g., I10 for essential hypertension, not R03.0).\n"
            "- For comorbidities, code each active condition that affects the encounter.\n"
            "- Map each ICD code to the correct SHA tariff code — mismatches trigger E006 rejection.\n"
            "- Quantity = actual units delivered (e.g., dialysis sessions, ANC visits).\n"
            "- SHA rates are fixed — do not adjust unit costs; flag if the facility's charge differs.\n"
            "- Never upcode (e.g., don't bill inpatient rates for outpatient visits).\n\n"
            "Your JSON output must be parseable. After the JSON array, add: CODING NOTES: <one paragraph>. "
            "Facilities are paid directly from your output — accuracy is revenue."
        )

    @property
    def capabilities(self) -> list:
        return ["icd10_coding", "sha_tariff_mapping", "claim_payload_construction"]

    async def process(self, message, intent, context, attachments=None) -> AgentResponse:
        return AgentResponse(agent=self.name, content="Use run() for SHA pipeline.", confidence=0.0)

    async def run(self, req: ClaimRequest, claim_id: str) -> CCEResult:
        # Fetch historical approval rates from Supabase tariff matrix
        tariff_intelligence: Dict[str, Any] = {}
        for item in req.line_items:
            conf = await get_tariff_confidence(item.icd_code)
            if conf:
                tariff_intelligence[item.icd_code] = conf

        # Build Sonnet coding prompt
        prompt = self._build_coding_prompt(req, tariff_intelligence)
        raw_response = await self._call_claude(
            messages=[{"role": "user", "content": prompt}],
            use_fable_model=True,
            max_tokens=4000,
            thinking_budget=2000,
        )

        mapped_items = self._parse_mappings(req, raw_response)
        total = sum(item.total for item in mapped_items)
        sha_payload = self._build_sha_payload(req, claim_id, mapped_items, total)

        return CCEResult(
            mapped_items=mapped_items,
            total_claim_amount=total,
            sha_claim_payload=sha_payload,
            coding_notes=raw_response[:600],
            confidence=0.93,
        )

    def _build_coding_prompt(self, req: ClaimRequest, tariff_intel: Dict) -> str:
        items_text = "\n".join(
            f"  - ICD: {i.icd_code} | {i.description} | Qty: {i.quantity} | Unit cost: KES {i.unit_cost}"
            for i in req.line_items
        )
        intel_text = json.dumps(tariff_intel, indent=2) if tariff_intel else "No historical data yet."
        return (
            f"FACILITY: {req.facility_id} | SCHEME: {req.patient.scheme} | ENCOUNTER: {req.encounter_type}\n"
            f"SERVICE DATE: {req.service_date}\n"
            f"PRESENTING COMPLAINT: {req.presenting_complaint}\n"
            f"PRIMARY DIAGNOSIS: {req.diagnosis}\n"
            f"CLINICAL NOTES: {req.clinical_notes or 'Not provided'}\n\n"
            f"SUBMITTED LINE ITEMS:\n{items_text}\n\n"
            f"HISTORICAL SHA APPROVAL RATES (from facility database):\n{intel_text}\n\n"
            "TASK: Produce a validated SHA coding for this claim.\n"
            "1. Correct any imprecise ICD-10 codes (e.g. I10 not R03.0 for hypertension).\n"
            "2. Map each to the correct SHA tariff code.\n"
            "3. Use SHA schedule rates (KES) — not the facility's charge.\n"
            "4. Assign confidence 0.0–1.0 per line (1.0 = no ambiguity).\n"
            "5. Note any E006 risk (tariff mismatch) or E003 risk (not in benefit package).\n\n"
            "OUTPUT FORMAT — write the JSON array first, then coding notes. "
            "Do NOT wrap the JSON in markdown fences:\n"
            "[\n"
            '  {"icd_code": "J18.9", "sha_tariff_code": "SHA-RESP-001", '
            '"tariff_desc": "Pneumonia management", "quantity": 1, '
            '"sha_rate": 2500, "total": 2500, "confidence": 0.95, "note": ""}\n'
            "]\n"
            "CODING NOTES: <one paragraph summary of coding decisions and any risks>"
        )

    def _parse_mappings(self, req: ClaimRequest, raw: str) -> List[CCEMappedItem]:
        items: List[CCEMappedItem] = []
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                for d in data:
                    items.append(CCEMappedItem(
                        icd_code=d.get("icd_code", "Z00.0"),
                        sha_tariff_code=d.get("sha_tariff_code", "SHA-CONSULT-001"),
                        tariff_description=d.get("tariff_desc", "Consultation"),
                        quantity=int(d.get("quantity", 1)),
                        sha_rate=float(d.get("sha_rate", 350)),
                        total=float(d.get("total", 350)),
                        mapping_confidence=float(d.get("confidence", 0.8)),
                    ))
        except Exception as e:
            logger.warning(f"CCE JSON parse failed, falling back to rule-based: {e}")

        if not items:
            items = self._rule_based_mapping(req)

        return items

    def _rule_based_mapping(self, req: ClaimRequest) -> List[CCEMappedItem]:
        items = []
        for li in req.line_items:
            tariff = SHA_TARIFF.get(li.icd_code, _CONSULT_CODE)
            rate = tariff["rate"]
            total = rate * li.quantity
            items.append(CCEMappedItem(
                icd_code=li.icd_code,
                sha_tariff_code=tariff["code"],
                tariff_description=tariff["desc"],
                quantity=li.quantity,
                sha_rate=float(rate),
                total=float(total),
                mapping_confidence=0.75,
            ))
        return items

    def _build_sha_payload(
        self, req: ClaimRequest, claim_id: str, items: List[CCEMappedItem], total: float
    ) -> Dict[str, Any]:
        return {
            "claimRef": claim_id,
            "facilityId": req.facility_id,
            "schemeCode": req.patient.scheme,
            "encounterType": req.encounter_type,
            "serviceDate": str(req.service_date),
            "patient": {
                "idNumber": req.patient.id_number,
                "name": req.patient.name,
                "gender": req.patient.gender,
                "memberId": req.patient.sha_member_id,
            },
            "diagnoses": [i.icd_code for i in items],
            "serviceLines": [
                {
                    "tariffCode": i.sha_tariff_code,
                    "description": i.tariff_description,
                    "icdCode": i.icd_code,
                    "quantity": i.quantity,
                    "unitCost": i.sha_rate,
                    "totalCost": i.total,
                }
                for i in items
            ],
            "totalClaimAmount": total,
            "currency": "KES",
            "submittedAt": date.today().isoformat(),
        }
