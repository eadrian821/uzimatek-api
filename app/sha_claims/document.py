"""SHA Claims — PDF generation and QR code utilities."""

import io
import base64
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from fpdf import FPDF
    _FPDF_OK = True
except ImportError:
    _FPDF_OK = False
    logger.warning("fpdf2 not installed. Run: pip install fpdf2")

try:
    import qrcode
    _QR_OK = True
except ImportError:
    _QR_OK = False
    logger.warning("qrcode not installed. Run: pip install 'qrcode[pil]'")


def generate_qr_bytes(
    claim_id: str,
    sha_ref: Optional[str] = None,
    base_url: str = "https://check.uzimatek.health",
) -> Optional[bytes]:
    """Return PNG bytes for a QR code encoding the claim lookup URL."""
    if not _QR_OK:
        return None

    # URL-first so any reader opens the portal; claim_id as fallback text
    content = f"{base_url}/c/{claim_id}"
    if sha_ref:
        content += f"\nSHA-REF:{sha_ref}"

    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=5,
        border=2,
    )
    qr.add_data(content)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_claim_pdf(claim: Dict[str, Any]) -> Optional[bytes]:
    """
    Generate an A4 SHA claim summary PDF.

    PDF contains: facility header + QR, patient info, encounter details,
    tariff breakdown, risk assessment, revenue projection, and footer.
    Returns bytes or None if fpdf2 is not installed.
    """
    if not _FPDF_OK:
        return None

    # ── Extract data ──────────────────────────────────────────────────────
    claim_id   = claim.get("claim_id") or "UNKNOWN"
    sha_ref    = claim.get("sha_ref") or "PENDING"
    status     = (claim.get("status") or "unknown").upper()
    facility   = claim.get("facility_id") or "DHABP00301"

    sha_payload    = claim.get("sha_payload") or {}
    patient        = sha_payload.get("patient") or {}
    service_lines  = sha_payload.get("serviceLines") or []
    diagnoses      = sha_payload.get("diagnoses") or claim.get("icd_codes") or []

    ebv    = claim.get("ebv_result") or {}
    paa    = claim.get("paa_result") or {}
    fadcpe = claim.get("fadcpe_result") or {}
    ri     = claim.get("ri_result") or {}

    total_amount    = float(claim.get("claim_amount") or sha_payload.get("totalClaimAmount") or 0)
    service_date    = sha_payload.get("serviceDate") or claim.get("service_date") or "—"
    encounter_type  = (sha_payload.get("encounterType") or claim.get("encounter_type") or "outpatient").title()
    scheme          = sha_payload.get("schemeCode") or claim.get("scheme") or "SHIF"

    # ── QR code ───────────────────────────────────────────────────────────
    qr_bytes = generate_qr_bytes(claim_id, sha_ref if sha_ref != "PENDING" else None)

    # ── Build PDF ─────────────────────────────────────────────────────────
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(14, 14, 14)
    pdf.set_auto_page_break(auto=True, margin=14)

    # ── Dark header bar ────────────────────────────────────────────────────
    pdf.set_fill_color(4, 13, 26)
    pdf.rect(0, 0, 210, 30, "F")

    pdf.set_xy(14, 7)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(0, 212, 170)
    pdf.cell(90, 7, "UZIMATEK")

    pdf.set_xy(14, 16)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(140, 175, 210)
    pdf.cell(90, 5, "SHA Claims Intelligence Platform")

    # Status badge (top right of header)
    _sc = {"APPROVED": (46, 213, 115), "REJECTED": (255, 71, 87)}.get(status, (255, 165, 2))
    pdf.set_fill_color(*_sc)
    pdf.set_text_color(10, 10, 10)
    pdf.set_font("Helvetica", "B", 8)
    pdf.rect(157, 9, 38, 12, "F")
    pdf.set_xy(157, 12)
    pdf.cell(38, 6, status, align="C")

    # QR code (right side, below header)
    if qr_bytes:
        pdf.image(io.BytesIO(qr_bytes), x=162, y=32, w=32)

    # ── Claim reference row ────────────────────────────────────────────────
    pdf.set_y(33)
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "SHA CLAIM SUMMARY", ln=True)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(70, 70, 70)
    pdf.cell(90, 5, f"Claim ID:  {claim_id}")
    pdf.cell(0,  5, f"SHA Reference:  {sha_ref}", ln=True)
    pdf.cell(90, 5, f"Facility:  {facility}")
    pdf.cell(0,  5, f"Generated:  {datetime.now().strftime('%Y-%m-%d %H:%M')} EAT", ln=True)

    pdf.set_draw_color(190, 210, 235)
    pdf.set_line_width(0.4)
    pdf.line(14, pdf.get_y() + 2, 196, pdf.get_y() + 2)
    pdf.ln(5)

    # ── Section helpers ────────────────────────────────────────────────────
    def section(title: str):
        pdf.set_fill_color(238, 248, 245)
        pdf.set_text_color(0, 130, 105)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.cell(0, 5.5, f"  {title}", ln=True, fill=True)
        pdf.ln(1)

    def kv(label: str, value: str, bold_val: bool = False):
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(110, 110, 110)
        pdf.cell(52, 5, f"{label}:")
        pdf.set_font("Helvetica", "B" if bold_val else "", 8)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 5, str(value), ln=True)

    # ── Patient ────────────────────────────────────────────────────────────
    section("PATIENT INFORMATION")
    kv("Name",         patient.get("name") or "—", bold_val=True)
    kv("National ID",  patient.get("idNumber") or "—")
    kv("SHA Member ID", patient.get("memberId") or "—")
    kv("Gender",       "Male" if patient.get("gender") == "M" else "Female" if patient.get("gender") == "F" else patient.get("gender") or "—")
    kv("Scheme",       scheme)
    pdf.ln(3)

    # ── Encounter ──────────────────────────────────────────────────────────
    section("ENCOUNTER DETAILS")
    kv("Encounter Type",  encounter_type)
    kv("Service Date",    service_date)
    kv("Diagnoses",       " · ".join(diagnoses) or "—")
    if ebv.get("eligible") is not None:
        kv("Eligibility", "ELIGIBLE ✓" if ebv["eligible"] else "NOT ELIGIBLE ✗")
    if paa.get("risk_level"):
        kv("Pre-Auth Risk", paa["risk_level"].upper())
    pdf.ln(3)

    # ── Tariff table ───────────────────────────────────────────────────────
    section("TARIFF BREAKDOWN")

    # Header row
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_fill_color(218, 232, 248)
    pdf.set_text_color(30, 60, 120)
    col_w = [22, 83, 13, 30, 30]
    for h, w in zip(["ICD", "Description", "Qty", "Rate (KES)", "Total (KES)"], col_w):
        pdf.cell(w, 6, h, border=1, fill=True, align="C" if w < 50 else "L")
    pdf.ln()

    # Data rows
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(20, 20, 20)
    for line in service_lines:
        total_line = float(line.get("totalCost") or 0)
        pdf.cell(22, 6, str(line.get("icdCode") or ""), border=1, align="C")
        pdf.cell(83, 6, str(line.get("description") or "")[:60], border=1)
        pdf.cell(13, 6, str(line.get("quantity") or 1), border=1, align="C")
        pdf.cell(30, 6, f"{float(line.get('unitCost') or 0):,.0f}", border=1, align="R")
        pdf.cell(30, 6, f"{total_line:,.0f}", border=1, align="R")
        pdf.ln()

    if not service_lines:
        pdf.cell(0, 6, "  No tariff lines — run the claims pipeline to generate.", border=1)
        pdf.ln()

    # Total row
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_fill_color(0, 185, 148)
    pdf.set_text_color(3, 35, 28)
    pdf.cell(148, 7, "TOTAL CLAIMED", border=1, fill=True, align="R")
    pdf.cell(30,  7, "KES",           border=1, fill=True, align="C")
    pdf.cell(30,  7, f"{total_amount:,.0f}", border=1, fill=True, align="R")
    pdf.ln(8)

    # ── FADCPE ────────────────────────────────────────────────────────────
    if fadcpe:
        section("RISK ASSESSMENT (FADCPE)")
        risk_score  = float(fadcpe.get("risk_score") or 0)
        clean_score = max(0, round((1 - risk_score) * 100))
        kv("Clean Score",   f"{clean_score} / 100")
        kv("Overall Risk",  (fadcpe.get("overall_risk") or "—").upper())
        flagged = fadcpe.get("flagged_codes") or []
        kv("Flagged Codes", ", ".join(flagged) if flagged else "None")
        for rec in (fadcpe.get("recommendations") or [])[:2]:
            pdf.set_font("Helvetica", "I", 7.5)
            pdf.set_text_color(90, 90, 90)
            pdf.cell(0, 4, f"  • {str(rec)[:120]}", ln=True)
        pdf.ln(3)

    # ── Revenue Intelligence ───────────────────────────────────────────────
    if ri:
        section("REVENUE PROJECTION (RI AGENT)")
        kv("Expected Payment",     f"KES {float(ri.get('expected_payment_amount') or 0):,.0f}", bold_val=True)
        kv("Approval Probability", f"{round(float(ri.get('expected_approval_rate') or 0) * 100)}%")
        kv("Days to Payment",      f"~{ri.get('expected_days_to_payment') or '—'} days ({scheme} standard)")
        pdf.ln(3)

    # ── Claim reference block (large, for staff to read/copy) ──────────────
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(0, 130, 105)
    pdf.cell(0, 5, "CLAIM REFERENCE (staff use)", ln=True)
    pdf.set_font("Courier", "B", 11)
    pdf.set_text_color(10, 10, 10)
    pdf.set_fill_color(238, 248, 245)
    pdf.cell(0, 9, f"  {claim_id}", ln=True, fill=True)
    pdf.ln(2)

    # ── Footer ────────────────────────────────────────────────────────────
    pdf.set_y(-22)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(14, pdf.get_y(), 196, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 4, f"Generated by Uzimatek Health Intelligence · {datetime.now().isoformat()[:19]} · {facility}", ln=True, align="C")
    pdf.cell(0, 4, "Scan QR code to check claim status online. Quote the Claim Reference when calling SHA.", ln=True, align="C")

    return bytes(pdf.output())
