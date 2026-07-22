"""Pydantic models for SHA claims pipeline I/O."""

from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class PatientInput(BaseModel):
    name: str
    id_number: str
    sha_member_id: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    scheme: str = "SHIF"


class ClaimLineItem(BaseModel):
    icd_code: str
    description: str
    quantity: int = 1
    unit_cost: float


class ClaimRequest(BaseModel):
    facility_id: str = "DHABP00301"
    patient: PatientInput
    encounter_type: str = "outpatient"
    service_date: date
    presenting_complaint: str
    diagnosis: str
    clinical_notes: Optional[str] = None
    line_items: List[ClaimLineItem]


class EBVResult(BaseModel):
    eligible: bool
    member_id: Optional[str] = None
    scheme: Optional[str] = None
    coverage_type: Optional[str] = None
    benefit_limits: Optional[Dict[str, Any]] = None
    raw_sha_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    confidence: float = 1.0


class PAAResult(BaseModel):
    pre_auth_required: bool
    risk_level: str  # low | medium | high
    recommendation: str
    reasoning: str
    flagged_items: List[str] = []
    confidence: float = 1.0


class CCEMappedItem(BaseModel):
    icd_code: str
    sha_tariff_code: str
    tariff_description: str
    quantity: int
    sha_rate: float
    total: float
    mapping_confidence: float
    historical_approval_rate: Optional[float] = None


class CCEResult(BaseModel):
    mapped_items: List[CCEMappedItem]
    total_claim_amount: float
    sha_claim_payload: Dict[str, Any]
    coding_notes: str
    confidence: float = 1.0


class FADCPEResult(BaseModel):
    overall_risk: str  # low | medium | high | critical
    risk_score: float
    per_code_scores: Dict[str, float]
    flagged_codes: List[str]
    recommendations: List[str]
    confidence: float = 1.0


class RIResult(BaseModel):
    expected_approval_rate: float
    expected_payment_amount: float
    expected_days_to_payment: int
    revenue_optimization_tips: List[str]
    appeal_strategy: Optional[str] = None
    confidence: float = 1.0


class ClaimSubmissionResult(BaseModel):
    sha_ref: Optional[str] = None
    status: str  # submitted | approved | rejected | pending | error
    rejection_code: Optional[str] = None
    rejection_reason: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class PipelineResult(BaseModel):
    claim_id: str
    facility_id: str
    status: str
    ebv: Optional[EBVResult] = None
    paa: Optional[PAAResult] = None
    cce: Optional[CCEResult] = None
    fadcpe: Optional[FADCPEResult] = None
    ri: Optional[RIResult] = None
    submission: Optional[ClaimSubmissionResult] = None
    total_duration_ms: int = 0
    error: Optional[str] = None
