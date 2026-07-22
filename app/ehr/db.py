"""Supabase REST CRUD layer for EHR tables.

All writes use fire-and-forget via asyncio.create_task where appropriate.
Reads are awaited. Uses httpx — same pattern as sha_claims/events.py.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE = None
_HEADERS = None


def _base() -> str:
    global _BASE
    if _BASE is None:
        _BASE = f"{settings.supabase_url}/rest/v1"
    return _BASE


def _h() -> Dict[str, str]:
    global _HEADERS
    if _HEADERS is None:
        _HEADERS = {
            "apikey": settings.supabase_key,
            "Authorization": f"Bearer {settings.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
    return _HEADERS


async def _get(path: str, params: Dict[str, str] = None) -> Any:
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(f"{_base()}{path}", params=params or {}, headers=_h())
        resp.raise_for_status()
        return resp.json()


async def _post(path: str, body: Dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.post(f"{_base()}{path}", json=body, headers=_h())
        resp.raise_for_status()
        return resp.json()


async def _patch(path: str, body: Dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.patch(f"{_base()}{path}", json=body, headers={**_h(), "Prefer": "return=representation"})
        resp.raise_for_status()
        return resp.json()


async def _delete(path: str) -> None:
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.delete(f"{_base()}{path}", headers={**_h(), "Prefer": "return=minimal"})
        resp.raise_for_status()


# ── Patients ──────────────────────────────────────────────────────────────────

async def list_patients(facility_id: str) -> List[Dict[str, Any]]:
    """Return all patients for a facility with full clinical sub-resources via parallel queries."""
    try:
        patients = await _get("/patients", {
            "facility_id": f"eq.{facility_id}",
            "order": "created_at.asc",
        })
        if not patients:
            return []

        pid_list = ",".join(p["id"] for p in patients)
        id_filter = f"in.({pid_list})"

        problems, vitals, labs, meds, notes, tasks = await asyncio.gather(
            _get("/problems",       {"patient_id": id_filter, "order": "created_at.asc"}),
            _get("/vitals",         {"patient_id": id_filter, "order": "recorded_at.asc"}),
            _get("/labs",           {"patient_id": id_filter, "order": "test_date.desc"}),
            _get("/medications",    {"patient_id": id_filter, "order": "created_at.asc"}),
            _get("/clinical_notes", {"patient_id": id_filter, "order": "note_date.desc"}),
            _get("/tasks",          {"patient_id": id_filter, "order": "created_at.asc"}),
        )

        def group(rows):
            d: Dict[str, list] = {}
            for r in (rows or []):
                d.setdefault(r["patient_id"], []).append(r)
            return d

        prob_map   = group(problems)
        vitals_map = group(vitals)
        labs_map   = group(labs)
        meds_map   = group(meds)
        notes_map  = group(notes)
        tasks_map  = group(tasks)

        return [_normalise_patient({
            **p,
            "problems":       prob_map.get(p["id"], []),
            "vitals":         vitals_map.get(p["id"], []),
            "labs":           labs_map.get(p["id"], []),
            "medications":    meds_map.get(p["id"], []),
            "clinical_notes": notes_map.get(p["id"], []),
            "tasks":          tasks_map.get(p["id"], []),
        }) for p in patients]
    except Exception as e:
        logger.error(f"list_patients error: {e}")
        return []


async def create_patient(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        rows = await _post("/patients", data)
        if isinstance(rows, list) and rows:
            return _normalise_patient(rows[0])
        return None
    except Exception as e:
        logger.error(f"create_patient error: {e}")
        raise


async def get_patient(patient_id: str) -> Optional[Dict[str, Any]]:
    try:
        rows = await _get("/patients", {"id": f"eq.{patient_id}"})
        if not rows:
            return None
        p = rows[0]
        id_filter = f"eq.{patient_id}"
        problems, vitals, labs, meds, notes, tasks = await asyncio.gather(
            _get("/problems",       {"patient_id": id_filter, "order": "created_at.asc"}),
            _get("/vitals",         {"patient_id": id_filter, "order": "recorded_at.asc"}),
            _get("/labs",           {"patient_id": id_filter, "order": "test_date.desc"}),
            _get("/medications",    {"patient_id": id_filter, "order": "created_at.asc"}),
            _get("/clinical_notes", {"patient_id": id_filter, "order": "note_date.desc"}),
            _get("/tasks",          {"patient_id": id_filter, "order": "created_at.asc"}),
        )
        return _normalise_patient({
            **p,
            "problems": problems, "vitals": vitals, "labs": labs,
            "medications": meds, "clinical_notes": notes, "tasks": tasks,
        })
    except Exception as e:
        logger.error(f"get_patient error: {e}")
        raise


def _normalise_patient(row: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten and normalise a Supabase patient row with embedded sub-resources."""
    name = row.get("name", "")
    parts = name.split()
    initials = "".join(p[0] for p in parts[:2]).upper() if parts else "??"

    vitals = sorted(
        row.get("vitals", []) or [],
        key=lambda v: v.get("recorded_at", ""),
    )
    notes = sorted(
        row.get("clinical_notes", []) or [],
        key=lambda n: n.get("note_date", ""),
        reverse=True,
    )

    return {
        "id": row["id"],
        "facility_id": row.get("facility_id", "DHABP00301"),
        "name": name,
        "initials": initials,
        "dob": row.get("dob"),
        "age": _age(row.get("dob")),
        "sex": row.get("gender", "M"),
        "id_number": row.get("id_number", ""),
        "sha_member_id": row.get("sha_member_id", ""),
        "scheme": row.get("scheme", "SHIF"),
        "ward": row.get("ward"),
        "bed": row.get("bed"),
        "admitted": row.get("admitted_at"),
        "attending": row.get("attending"),
        "risk": row.get("risk", "low"),
        "eligibility_status": row.get("eligibility_status", "unknown"),
        "problems": row.get("problems", []) or [],
        "vitals_history": vitals,
        "labs": sorted(row.get("labs", []) or [], key=lambda l: l.get("test_date", ""), reverse=True),
        "meds": row.get("medications", []) or [],
        "notes": notes,
        "tasks": row.get("tasks", []) or [],
        "created_at": row.get("created_at"),
    }


def _age(dob: Optional[str]) -> Optional[int]:
    if not dob:
        return None
    try:
        from datetime import date as d
        birth = d.fromisoformat(dob[:10])
        today = d.today()
        return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    except Exception:
        return None


# ── Problems ──────────────────────────────────────────────────────────────────

async def add_problem(patient_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    rows = await _post("/problems", {"patient_id": patient_id, **data})
    return rows[0] if isinstance(rows, list) and rows else rows


async def delete_problem(problem_id: str) -> None:
    await _delete(f"/problems?id=eq.{problem_id}")


# ── Vitals ────────────────────────────────────────────────────────────────────

async def add_vitals(patient_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if "recorded_at" not in data or not data["recorded_at"]:
        data["recorded_at"] = datetime.now(timezone.utc).isoformat()
    rows = await _post("/vitals", {"patient_id": patient_id, **data})
    return rows[0] if isinstance(rows, list) and rows else rows


async def list_vitals(patient_id: str) -> List[Dict[str, Any]]:
    return await _get("/vitals", {
        "patient_id": f"eq.{patient_id}",
        "order": "recorded_at.asc",
    })


# ── Labs ──────────────────────────────────────────────────────────────────────

async def add_lab(patient_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not data.get("test_date"):
        from datetime import date
        data["test_date"] = date.today().isoformat()
    rows = await _post("/labs", {"patient_id": patient_id, **data})
    return rows[0] if isinstance(rows, list) and rows else rows


async def delete_lab(lab_id: str) -> None:
    await _delete(f"/labs?id=eq.{lab_id}")


# ── Medications ───────────────────────────────────────────────────────────────

async def add_medication(patient_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    rows = await _post("/medications", {"patient_id": patient_id, **data})
    return rows[0] if isinstance(rows, list) and rows else rows


async def delete_medication(med_id: str) -> None:
    await _delete(f"/medications?id=eq.{med_id}")


# ── Notes ─────────────────────────────────────────────────────────────────────

async def add_note(patient_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not data.get("note_date"):
        from datetime import date
        data["note_date"] = date.today().isoformat()
    rows = await _post("/clinical_notes", {"patient_id": patient_id, **data})
    return rows[0] if isinstance(rows, list) and rows else rows


async def list_notes(patient_id: str) -> List[Dict[str, Any]]:
    return await _get("/clinical_notes", {
        "patient_id": f"eq.{patient_id}",
        "order": "note_date.desc",
    })


# ── Tasks ─────────────────────────────────────────────────────────────────────

async def add_task(patient_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    rows = await _post("/tasks", {"patient_id": patient_id, **data})
    return rows[0] if isinstance(rows, list) and rows else rows


async def toggle_task(task_id: str, done: bool) -> Dict[str, Any]:
    rows = await _patch(f"/tasks?id=eq.{task_id}", {"done": done})
    return rows[0] if isinstance(rows, list) and rows else rows


# ── Training outcomes ─────────────────────────────────────────────────────────

async def log_training_outcome(data: Dict[str, Any]) -> Dict[str, Any]:
    """Log a real SHA outcome for agent calibration / fine-tuning."""
    rows = await _post("/training_outcomes", data)

    # Also update the tariff confidence matrix
    if data.get("cce_tariff_codes"):
        outcome = data.get("actual_outcome")
        rejection = data.get("rejection_code")
        for tariff_code in data["cce_tariff_codes"]:
            asyncio.create_task(_update_tariff_matrix(tariff_code, outcome, rejection))

    return rows[0] if isinstance(rows, list) and rows else rows


async def _update_tariff_matrix(tariff_code: str, outcome: str, rejection_code: Optional[str]) -> None:
    """Increment the tariff confidence matrix for this tariff code."""
    try:
        approved = 1 if outcome == "approved" else 0
        e006 = 1 if rejection_code == "E006" else 0
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{_base()}/tariff_confidence_matrix",
                json={
                    "icd_code": "UNKNOWN",
                    "sha_tariff_code": tariff_code,
                    "n_submissions": 1,
                    "n_approved": approved,
                    "n_rejected_e006": e006,
                },
                headers={**_h(), "Prefer": "resolution=merge-duplicates,return=minimal"},
            )
    except Exception as e:
        logger.warning(f"Tariff matrix update failed for {tariff_code}: {e}")
