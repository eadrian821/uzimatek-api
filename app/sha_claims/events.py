"""Claim lifecycle event logger — fire-and-forget to Supabase REST."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

_SUPABASE_HEADERS: Optional[Dict[str, str]] = None
_http_client: Optional[httpx.AsyncClient] = None


def _headers() -> Dict[str, str]:
    global _SUPABASE_HEADERS
    if _SUPABASE_HEADERS is None:
        _SUPABASE_HEADERS = {
            "apikey": settings.supabase_key,
            "Authorization": f"Bearer {settings.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
    return _SUPABASE_HEADERS


def _client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client


async def log_event(
    claim_id: str,
    facility_id: str,
    event_type: str,
    payload: Dict[str, Any],
    agent_predictions: Optional[Dict[str, Any]] = None,
    sha_data: Optional[Dict[str, Any]] = None,
) -> None:
    row: Dict[str, Any] = {
        "claim_id": claim_id,
        "facility_id": facility_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    if agent_predictions is not None:
        row["agent_predictions"] = agent_predictions
    if sha_data is not None:
        row["sha_data"] = sha_data

    async def _post() -> None:
        try:
            resp = await _client().post(
                f"{settings.supabase_url}/rest/v1/claim_events",
                json=row,
                headers=_headers(),
            )
            if resp.status_code not in (200, 201):
                logger.warning(f"Event log HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Event log error [{event_type}]: {e}")

    asyncio.create_task(_post())


async def upsert_claim(claim_data: Dict[str, Any]) -> None:
    async def _upsert() -> None:
        try:
            resp = await _client().post(
                f"{settings.supabase_url}/rest/v1/sha_claims",
                json=claim_data,
                headers={
                    **_headers(),
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
            )
            if resp.status_code not in (200, 201):
                logger.warning(f"Claim upsert HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Claim upsert error: {e}")

    asyncio.create_task(_upsert())


async def get_facility_stats(facility_id: str) -> Dict[str, Any]:
    try:
        resp = await _client().get(
            f"{settings.supabase_url}/rest/v1/sha_claims",
            params={
                "facility_id": f"eq.{facility_id}",
                "select": "status,claim_amount,approved_amount",
                "limit": "1000",
            },
            headers=_headers(),
        )
        if resp.status_code != 200:
            return {}
        rows = resp.json()
        total = len(rows)
        approved = sum(1 for r in rows if r.get("status") == "approved")
        submitted = sum(1 for r in rows if r.get("status") == "submitted")
        rejected = sum(1 for r in rows if r.get("status") == "rejected")
        total_claimed = sum(float(r.get("claim_amount") or 0) for r in rows)
        total_approved = sum(float(r.get("approved_amount") or 0) for r in rows)
        return {
            "total": total,
            "approved": approved,
            "submitted": submitted,
            "rejected": rejected,
            "pending": max(0, total - approved - submitted - rejected),
            "approval_rate": round(approved / total, 3) if total else 0,
            "total_claimed_kes": total_claimed,
            "total_approved_kes": total_approved,
        }
    except Exception as e:
        logger.error(f"Stats fetch error: {e}")
        return {}


async def get_claims_list(facility_id: str, limit: int = 50) -> list:
    try:
        resp = await _client().get(
            f"{settings.supabase_url}/rest/v1/sha_claims",
            params={
                "facility_id": f"eq.{facility_id}",
                "select": "claim_id,status,scheme,encounter_type,service_date,claim_amount,sha_ref,created_at,sha_payload",
                "order": "created_at.desc",
                "limit": str(limit),
            },
            headers=_headers(),
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception as e:
        logger.error(f"Claims list error: {e}")
        return []


async def get_claim_by_id(claim_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single claim with all agent result fields (select=*)."""
    try:
        resp = await _client().get(
            f"{settings.supabase_url}/rest/v1/sha_claims",
            params={"claim_id": f"eq.{claim_id}", "select": "*", "limit": "1"},
            headers=_headers(),
        )
        if resp.status_code == 200:
            rows = resp.json()
            return rows[0] if rows else None
        logger.warning(f"get_claim_by_id HTTP {resp.status_code} for {claim_id}")
        return None
    except Exception as e:
        logger.error(f"get_claim_by_id error: {e}")
        return None


async def get_tariff_confidence(icd_code: str) -> Dict[str, Any]:
    try:
        resp = await _client().get(
            f"{settings.supabase_url}/rest/v1/tariff_confidence_matrix",
            params={"icd_code": f"eq.{icd_code}", "order": "n_submissions.desc"},
            headers=_headers(),
        )
        if resp.status_code == 200:
            rows = resp.json()
            return {r["sha_tariff_code"]: {
                "n_submissions": r["n_submissions"],
                "n_approved": r["n_approved"],
                "approval_rate": round(r["n_approved"] / r["n_submissions"], 3) if r["n_submissions"] > 0 else None,
            } for r in rows}
        return {}
    except Exception as e:
        logger.error(f"Tariff confidence error: {e}")
        return {}
