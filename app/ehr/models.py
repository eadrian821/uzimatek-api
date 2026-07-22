"""Pydantic models for EHR CRUD endpoints."""

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


# ── Request bodies ─────────────────────────────────────────────────────────────

class PatientCreate(BaseModel):
    name: str
    id_number: str
    sha_member_id: Optional[str] = None
    dob: Optional[str] = None
    gender: str = "M"
    scheme: str = "SHIF"
    ward: Optional[str] = None
    bed: Optional[str] = None
    admitted_at: Optional[str] = None
    attending: Optional[str] = None
    risk: str = "low"
    facility_id: str = "DHABP00301"


class ProblemCreate(BaseModel):
    icd_code: str
    name: str
    severity: str = "mild"
    since: Optional[str] = None
    status: str = "Active"


class VitalsCreate(BaseModel):
    recorded_at: Optional[datetime] = None
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    heart_rate: Optional[int] = None
    spo2: Optional[float] = None
    temperature: Optional[float] = None
    respiratory_rate: Optional[int] = None


class LabCreate(BaseModel):
    test_name: str
    value: str
    unit: Optional[str] = None
    ref_range: Optional[str] = None
    flag: Optional[str] = None
    test_date: Optional[str] = None


class MedicationCreate(BaseModel):
    name: str
    dose: str
    frequency: str = "OD"
    route: str = "PO"
    indication: Optional[str] = None
    start_year: Optional[str] = None


class NoteCreate(BaseModel):
    note_type: str = "Progress"
    author: Optional[str] = None
    soap_text: str
    note_date: Optional[str] = None


class TaskCreate(BaseModel):
    label: str
    due: Optional[str] = None


class TaskToggle(BaseModel):
    done: bool


class TrainingOutcome(BaseModel):
    claim_id: str
    facility_id: str = "DHABP00301"
    sha_ref: Optional[str] = None
    actual_outcome: str                  # approved | rejected | partial
    rejection_code: Optional[str] = None
    actual_payment_kes: Optional[float] = None
    days_to_payment: Optional[int] = None
    fadcpe_predicted_risk: Optional[str] = None
    fadcpe_predicted_score: Optional[float] = None
    ri_predicted_rate: Optional[float] = None
    ri_predicted_days: Optional[int] = None
    cce_tariff_codes: Optional[List[str]] = None
    notes: Optional[str] = None
