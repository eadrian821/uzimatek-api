"""Authenticated HTTP client for SHA UAT (api-uat.tiberbu.health)."""

import base64
import logging
import time
from typing import Any, Dict, Optional

import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_CONNECT = 15.0
_TIMEOUT_READ = 45.0


class SHAClient:
    def __init__(self) -> None:
        self.base_url = getattr(settings, "sha_uat_url", "https://api-uat.tiberbu.health").rstrip("/")
        self.facility_id = getattr(settings, "sha_facility_id", "DHABP00301")
        self.org_id = getattr(settings, "sha_org_id", "8TI-DHABP00301")
        self._jwt: Optional[str] = None
        self._jwt_expires_at: float = 0.0

    async def _get_token(self) -> str:
        now = time.monotonic()
        if self._jwt and now < self._jwt_expires_at - 60:
            return self._jwt

        username = getattr(settings, "sha_username", "") or ""
        password = getattr(settings, "sha_password", "") or ""
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_TIMEOUT_CONNECT, read=_TIMEOUT_READ),
            verify=False,
        ) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/api/v1/auth/token",
                    headers={"Authorization": f"Basic {credentials}"},
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        token = data.get("token") or data.get("access_token") or data.get("jwt")
                        expires_in = data.get("expires_in", 3600)
                    except Exception:
                        token = resp.text.strip()
                        expires_in = 3600
                    if not token:
                        raise ValueError("SHA auth returned empty token")
                    self._jwt = token
                    self._jwt_expires_at = now + expires_in
                    return self._jwt
                else:
                    raise ValueError(f"SHA auth {resp.status_code}: {resp.text[:200]}")
            except httpx.TimeoutException:
                raise ValueError("SHA UAT auth endpoint timed out (522)")

    def _headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Facility-ID": self.facility_id,
            "X-Org-ID": self.org_id,
        }

    async def check_eligibility(self, id_number: str, scheme: str = "SHIF") -> Dict[str, Any]:
        try:
            token = await self._get_token()
        except Exception as e:
            return {"status_code": 0, "data": None, "error": str(e)}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_TIMEOUT_CONNECT, read=_TIMEOUT_READ), verify=False
        ) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/api/v1/members/{id_number}/eligibility",
                    params={"facility_id": self.facility_id, "scheme": scheme},
                    headers=self._headers(token),
                )
                ok = resp.status_code in (200, 201)
                return {
                    "status_code": resp.status_code,
                    "data": resp.json() if ok else None,
                    "error": resp.text[:300] if not ok else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 522, "data": None, "error": "SHA UAT connection timeout (522)"}
            except Exception as e:
                return {"status_code": 0, "data": None, "error": str(e)}

    async def submit_claim(self, claim_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            token = await self._get_token()
        except Exception as e:
            return {"status_code": 0, "data": None, "error": str(e)}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_TIMEOUT_CONNECT, read=60.0), verify=False
        ) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/v1/claims",
                    json=claim_payload,
                    headers=self._headers(token),
                )
                ok = resp.status_code in (200, 201, 202)
                return {
                    "status_code": resp.status_code,
                    "data": resp.json() if ok else None,
                    "error": resp.text[:300] if not ok else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 522, "data": None, "error": "SHA UAT connection timeout (522)"}
            except Exception as e:
                return {"status_code": 0, "data": None, "error": str(e)}

    async def get_claim_status(self, sha_ref: str) -> Dict[str, Any]:
        try:
            token = await self._get_token()
        except Exception as e:
            return {"status_code": 0, "data": None, "error": str(e)}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_TIMEOUT_CONNECT, read=_TIMEOUT_READ), verify=False
        ) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/api/v1/claims/{sha_ref}",
                    headers=self._headers(token),
                )
                ok = resp.status_code == 200
                return {
                    "status_code": resp.status_code,
                    "data": resp.json() if ok else None,
                    "error": resp.text[:300] if not ok else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 522, "data": None, "error": "SHA UAT connection timeout (522)"}
            except Exception as e:
                return {"status_code": 0, "data": None, "error": str(e)}


sha_client = SHAClient()
