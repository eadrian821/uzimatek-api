"""
SHA Kenya Claims Rejection Code Framework — E001–E020

Each code includes:
- description: What SHA's adjudication engine returns
- root_cause: Why it triggers
- fix_action: What the billing team must do
- appealable: Whether SHA accepts appeals for this code
- appeal_window_days: Days from rejection notice to file appeal
- appeal_evidence: Documents required for a successful appeal
- prevention: How to avoid it at source
- frequency: 'common' | 'occasional' | 'rare'

Used by: FADCPE agent, pipeline.py, router.py appeal endpoint.
"""

from typing import Dict, List, Optional


class RejectionCodeInfo:
    def __init__(self, *, code, description, root_cause, fix_action,
                 appealable, appeal_window_days, appeal_evidence,
                 prevention, frequency):
        self.code = code
        self.description = description
        self.root_cause = root_cause
        self.fix_action = fix_action
        self.appealable = appealable
        self.appeal_window_days = appeal_window_days
        self.appeal_evidence: List[str] = appeal_evidence
        self.prevention = prevention
        self.frequency = frequency

    def to_dict(self) -> Dict:
        return self.__dict__


REJECTION_CODES: Dict[str, RejectionCodeInfo] = {
    "E001": RejectionCodeInfo(
        code="E001",
        description="Member not found in SHA national registry",
        root_cause="SHA member ID or national ID does not match any active SHA member record.",
        fix_action="Verify member details at SHA member portal (members.sha.go.ke). Check for data entry errors. Confirm member completed SHA/NHIF registration.",
        appealable=False,
        appeal_window_days=0,
        appeal_evidence=[],
        prevention="Run live EBV check at registration. Capture SHA member card number at first visit.",
        frequency="common",
    ),
    "E002": RejectionCodeInfo(
        code="E002",
        description="Member not covered on date of service",
        root_cause="Member's SHA coverage was lapsed, suspended, or not yet active on the service date.",
        fix_action="Verify coverage dates in SHA portal. If member paid premiums, obtain contribution receipt and request coverage reinstatement. Check if employer posted contribution late.",
        appealable=False,
        appeal_window_days=0,
        appeal_evidence=[],
        prevention="Run live EBV at point of service. Check coverage dates explicitly — eligibility 'active' status may not reflect latest payment lapse.",
        frequency="common",
    ),
    "E003": RejectionCodeInfo(
        code="E003",
        description="Service not included in member's benefit package",
        root_cause="The billed tariff code is not covered under the member's active SHA scheme (SHIF/Linda Mama/CSPS).",
        fix_action="Review SHA benefit schedule for the specific scheme. Appeal if service is clinically necessary and within broad SHIF benefit coverage. Some exclusions are overridable with specialist authorization.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "SHA benefit schedule reference showing service should be covered",
            "Clinical necessity documentation signed by consultant",
            "Specialist recommendation letter",
            "SHA scheme benefit package extract confirming coverage intention",
        ],
        prevention="Map tariff codes to correct scheme benefit packages before submission. Use CCE agent scheme validation flag.",
        frequency="occasional",
    ),
    "E004": RejectionCodeInfo(
        code="E004",
        description="Insufficient supporting documentation",
        root_cause="Required clinical documents missing: clinical notes, lab results, imaging, referral letters, or consent forms.",
        fix_action="Attach complete documentation: SOAP notes, investigations, specialist referral (if applicable), consent forms, and procedure reports.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "Complete SOAP clinical notes signed by attending clinician",
            "Laboratory investigation results with reference ranges",
            "Imaging reports (X-ray, CT, MRI, ultrasound)",
            "Specialist referral letter",
            "Signed patient consent form",
            "Surgical or procedure report",
            "Discharge summary",
        ],
        prevention="Complete clinical documentation before claim submission. FADCPE E004 flag triggers documentation checklist.",
        frequency="common",
    ),
    "E005": RejectionCodeInfo(
        code="E005",
        description="Duplicate claim submission",
        root_cause="A claim for the same member, service date, facility, and tariff code was already received within the 30-day detection window.",
        fix_action="Check SHA portal for existing claim reference. If original claim was rejected, reference that rejection in resubmission citing the rejection code and correction made.",
        appealable=False,
        appeal_window_days=0,
        appeal_evidence=[],
        prevention="Maintain internal claim ID register. Run duplicate check against SHA portal before submission. Never resubmit without first checking portal claim status.",
        frequency="occasional",
    ),
    "E006": RejectionCodeInfo(
        code="E006",
        description="Tariff code does not match ICD-10 diagnosis code",
        root_cause="SHA tariff code submitted does not correspond to the ICD-10 diagnosis per the SHA tariff schedule. Most common coding error.",
        fix_action="Review SHA tariff schedule. Correct tariff code to match ICD-10 exactly. Use CCE agent to re-validate the ICD→tariff mapping. Resubmit with corrected coding.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "Corrected tariff-ICD mapping with SHA tariff schedule reference page",
            "Clinical notes supporting the specific diagnosis",
            "ICD-10 coding rationale from clinical coder",
            "SHA tariff schedule extract showing correct code pairing",
        ],
        prevention="Use CCE agent for all claims — it maps ICD-10 → SHA tariff with confidence scoring. Flag low-confidence mappings for manual review.",
        frequency="common",
    ),
    "E007": RejectionCodeInfo(
        code="E007",
        description="Pre-authorization required but not obtained",
        root_cause="Service required SHA pre-authorization (inpatient >24h, elective surgery, dialysis, chemotherapy, MRI/CT, cardiac procedures) but pre-auth reference number was absent.",
        fix_action="For emergencies: obtain retrospective pre-auth within 24h of admission. For elective services: pre-auth is NOT retroactively grantable — absorb as bad debt or charge patient. File a service recovery plan with SHA.",
        appealable=False,
        appeal_window_days=0,
        appeal_evidence=[],
        prevention="Run PAA check at service entry. Obtain pre-auth number from SHA portal BEFORE elective service delivery. Emergency: get pre-auth reference within 24h.",
        frequency="common",
    ),
    "E008": RejectionCodeInfo(
        code="E008",
        description="Claim submitted outside the 90-day window",
        root_cause="Claim submitted more than 90 days after the date of service. SHA rejects late claims except in documented exceptional circumstances.",
        fix_action="Submit late submission appeal with documented reason: system downtime, natural disaster, hospitalization of billing staff. Approval is discretionary.",
        appealable=True,
        appeal_window_days=14,
        appeal_evidence=[
            "Documentary evidence of exceptional circumstance causing delay",
            "System downtime certificate (if IT failure — from vendor)",
            "Facility operations report covering the delay period",
            "SHA or NHIF acknowledgement of any known delays in the period",
        ],
        prevention="Implement 30/60/90-day submission deadline alerts. Target submission within 30 days as best practice. Batch claims weekly.",
        frequency="occasional",
    ),
    "E009": RejectionCodeInfo(
        code="E009",
        description="Facility not accredited for the billed service level",
        root_cause="Facility's SHA accreditation tier does not cover the service delivered (e.g., Level 2 facility billing Level 5 surgical procedures).",
        fix_action="Review facility accreditation certificate for eligible service categories. For services genuinely delivered, apply for emergency facility tier upgrade or appeal with evidence service is within scope.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "Current SHA/Kenya Medical Practitioners facility accreditation certificate",
            "SHA facility tier classification document",
            "Evidence service was delivered within facility's clinical scope",
            "MOH facility registration certificate",
        ],
        prevention="Review SHA accreditation tier before billing high-level procedures. Upgrade tier proactively if scope of services has expanded.",
        frequency="rare",
    ),
    "E010": RejectionCodeInfo(
        code="E010",
        description="Annual benefit limit exceeded",
        root_cause="Member has exhausted the annual benefit cap for this service category under their scheme.",
        fix_action="Check remaining benefit balance via SHA portal. Patient pays top-up for excess amount. Consider patient payment plan. Document benefit exhaustion in patient file.",
        appealable=False,
        appeal_window_days=0,
        appeal_evidence=[],
        prevention="Check benefit balance before elective service delivery. Inform patients of coverage limits. SHA portal shows real-time balance per member.",
        frequency="occasional",
    ),
    "E011": RejectionCodeInfo(
        code="E011",
        description="Provider not contracted with SHA",
        root_cause="Facility's SHA contract has expired, was suspended, or was never executed.",
        fix_action="Renew SHA facility contract immediately. Claims submitted while uncontracted are not payable retroactively. Escalate to facility CEO for contract reinstatement.",
        appealable=False,
        appeal_window_days=0,
        appeal_evidence=[],
        prevention="Set SHA contract expiry alerts 90 days in advance. Assign contract renewal responsibility to finance manager.",
        frequency="rare",
    ),
    "E012": RejectionCodeInfo(
        code="E012",
        description="Invalid or expired referral",
        root_cause="Service required referral (SHIF Level 2→3→4→5 gatekeeping) but referral was absent, invalid, or expired (typically valid for 3 months).",
        fix_action="Obtain valid referral letter from appropriate referring facility. For retrospective referrals, provide documentation of clinical urgency. Referrals must be on facility letterhead with practitioner stamp.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "Referral letter from referring facility on facility letterhead",
            "Clinical urgency documentation explaining why referral was not pre-obtained",
            "Patient registration record at referring facility",
            "Emergency presentation evidence if applicable",
        ],
        prevention="Collect referral letters at reception as mandatory admission document. Validate referral date. Self-referrals for specialist services trigger E012.",
        frequency="occasional",
    ),
    "E013": RejectionCodeInfo(
        code="E013",
        description="Service date mismatch",
        root_cause="Service date on SHA claim does not match facility EMR, appointment register, or OPD book.",
        fix_action="Reconcile dates between billing system and clinical records. Submit corrected claim with supporting OPD/admission register entry.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "OPD/admission register extract showing correct service date",
            "Patient appointment records",
            "Clinical notes with correct date",
            "Pharmacy dispensing record dated correctly",
        ],
        prevention="Implement billing-EMR date validation gate before claim generation. Pharmacy timestamps are authoritative.",
        frequency="occasional",
    ),
    "E014": RejectionCodeInfo(
        code="E014",
        description="Prescription or procedure not clinically indicated for diagnosis",
        root_cause="Medications or procedures billed are not standard of care for the stated ICD-10 diagnosis in SHA's clinical rules engine.",
        fix_action="Provide clinical justification or add comorbidity ICD codes that establish the indication. Include clinical guidelines reference.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "Clinical notes establishing the indication",
            "Specialist recommendation for the off-label or complex regimen",
            "Clinical guideline reference (KNF, WHO, international society)",
            "Additional ICD-10 codes establishing comorbidity indication",
        ],
        prevention="Code all active comorbidities — multi-morbidity is common in MTRH patients and establishes indication for complex regimens.",
        frequency="occasional",
    ),
    "E015": RejectionCodeInfo(
        code="E015",
        description="Quantity exceeds SHA schedule maximum",
        root_cause="Units billed (days, sessions, tablets, tests) exceed the maximum allowed by SHA tariff schedule for that code.",
        fix_action="Review SHA tariff quantity caps. Rebill at maximum allowed. Apply for exceptional authorization for medically necessary excess.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "Clinical justification for quantity exceeding schedule",
            "SHA exceptional authorization request",
            "Specialist recommendation for extended treatment course",
            "Patient outcome data supporting continued service",
        ],
        prevention="Flag high-quantity orders for pre-authorization before service delivery.",
        frequency="occasional",
    ),
    "E016": RejectionCodeInfo(
        code="E016",
        description="Claim submitted for deceased member",
        root_cause="SHA records show member deceased before service date, or SHA received death notification before claim was processed.",
        fix_action="If service was delivered before death, appeal with certified death certificate showing date of death after service date. Include clinical records proving service.",
        appealable=True,
        appeal_window_days=14,
        appeal_evidence=[
            "Certified death certificate with exact date of death",
            "Clinical notes or OPD register proving service pre-dated death",
            "Discharge summary if patient left facility alive",
        ],
        prevention="Run live EBV at service point — SHA member death triggers eligibility change. Check member status same day.",
        frequency="rare",
    ),
    "E017": RejectionCodeInfo(
        code="E017",
        description="Claim amount exceeds SHA tariff rate",
        root_cause="Unit cost or total claimed exceeds the gazetted SHA tariff rate. SHA pays fixed tariff rates regardless of facility charges.",
        fix_action="Rebill at SHA schedule rate. The excess is facility responsibility — write off or bill patient for the difference above tariff. SHA does not negotiate claim-by-claim rates.",
        appealable=False,
        appeal_window_days=0,
        appeal_evidence=[],
        prevention="Always use SHA schedule rates for claim submission. Separate facility cost accounting from SHA billing. CCE agent applies correct SHA rates automatically.",
        frequency="common",
    ),
    "E018": RejectionCodeInfo(
        code="E018",
        description="Required co-payment not documented",
        root_cause="SHA scheme requires patient cost-sharing for this service and documentation of collection was missing or waiver was undocumented.",
        fix_action="Attach patient payment receipt. If co-payment was waived (indigent/hardship), provide social worker waiver form.",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "Patient payment receipt with amount",
            "Waiver form if co-payment was waived",
            "Means assessment record for hardship waiver",
            "Social work referral documentation",
        ],
        prevention="Generate official receipts for all co-payments. Keep originals in billing file. Train reception staff on co-payment documentation requirements.",
        frequency="rare",
    ),
    "E019": RejectionCodeInfo(
        code="E019",
        description="Provider-member gatekeeping relationship not established",
        root_cause="Member is registered at a different primary SHA provider under SHIF's gatekeeping model and was not properly referred.",
        fix_action="Obtain confirmation from member's primary SHA facility that referral was authorized, or confirm service was emergency (waives gatekeeping).",
        appealable=True,
        appeal_window_days=30,
        appeal_evidence=[
            "Emergency presentation evidence waiving gatekeeping requirement",
            "Primary facility referral confirmation letter",
            "SHA member registration record showing primary facility assignment",
        ],
        prevention="At registration, collect SHA card showing primary facility. For SHIF gatekeeping, obtain referral from primary facility before specialist service.",
        frequency="rare",
    ),
    "E020": RejectionCodeInfo(
        code="E020",
        description="Claim data integrity failure — missing or malformed fields",
        root_cause="Required claim fields are null, wrongly formatted, or structurally invalid in the SHA API submission (invalid date, missing facility ID, etc.).",
        fix_action="Review claim JSON against SHA API specification. Correct all required fields. Resubmit with valid data structure.",
        appealable=False,
        appeal_window_days=0,
        appeal_evidence=[],
        prevention="Use validated claim builder. Run SHA schema validation before submission. CCE agent constructs the payload — review output before sending to SHA UAT.",
        frequency="occasional",
    ),
}

APPEALABLE_CODES = {code for code, info in REJECTION_CODES.items() if info.appealable}
COMMON_CODES = {code for code, info in REJECTION_CODES.items() if info.frequency == "common"}


def get_rejection_info(code: str) -> Optional[RejectionCodeInfo]:
    return REJECTION_CODES.get(code.upper())


def build_appeal_template(
    code: str,
    claim_id: str,
    facility_id: str,
    patient_name: str,
    service_date: str,
    claim_amount: float,
    sha_ref: Optional[str] = None,
) -> Optional[str]:
    """Return a structured SHA appeal letter template for an appealable rejection code."""
    info = get_rejection_info(code)
    if not info or not info.appealable:
        return None

    evidence = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(info.appeal_evidence))

    return (
        f"SHA KENYA — CLAIM APPEAL LETTER\n"
        f"{'='*62}\n\n"
        f"TO: SHA Kenya Claims Appeals Unit\n"
        f"FROM: {facility_id}\n\n"
        f"Claim Reference:  {claim_id}\n"
        f"SHA Reference:    {sha_ref or 'PENDING'}\n"
        f"Patient:          {patient_name}\n"
        f"Service Date:     {service_date}\n"
        f"Claimed Amount:   KES {claim_amount:,.2f}\n"
        f"Rejection Code:   {code} — {info.description}\n\n"
        f"GROUNDS FOR APPEAL\n"
        f"{'-'*40}\n"
        f"The facility respectfully appeals the rejection of the above claim.\n\n"
        f"Root cause identified: {info.root_cause}\n\n"
        f"Remedial action taken: {info.fix_action}\n\n"
        f"SUPPORTING EVIDENCE (ATTACHED)\n"
        f"{'-'*40}\n"
        f"{evidence}\n\n"
        f"REQUESTED OUTCOME\n"
        f"{'-'*40}\n"
        f"We request full review and re-adjudication. The service was clinically\n"
        f"necessary and delivered in accordance with SHA guidelines. All supporting\n"
        f"documentation is compiled above.\n\n"
        f"This appeal is filed within the {info.appeal_window_days}-day window as\n"
        f"required by SHA Kenya claims regulations.\n\n"
        f"{'='*62}\n"
        f"Authorized by: ______________________  Date: ____________\n"
        f"Title: Claims Manager, {facility_id}\n"
    )


def get_all_codes_summary() -> List[Dict]:
    """Return a list of all rejection codes as dicts — used by the tariff reference endpoint."""
    return [
        {
            "code": info.code,
            "description": info.description,
            "root_cause": info.root_cause,
            "fix_action": info.fix_action,
            "appealable": info.appealable,
            "appeal_window_days": info.appeal_window_days,
            "prevention": info.prevention,
            "frequency": info.frequency,
        }
        for info in REJECTION_CODES.values()
    ]
