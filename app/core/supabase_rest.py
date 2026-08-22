from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol


DEFAULT_PREFER = "resolution=merge-duplicates,return=representation"
SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class HttpTransport(Protocol):
    def get(self, url: str, **kwargs): ...
    def post(self, url: str, **kwargs): ...
    def patch(self, url: str, **kwargs): ...
    def delete(self, url: str, **kwargs): ...


@dataclass(frozen=True)
class SupabaseRestClient:
    """Small transport boundary for Supabase's PostgREST API.

    Keeping HTTP details here prevents storage concerns from leaking into the
    account, OAuth, automation, and dashboard repositories.
    """

    base_url: str
    service_role_key: str
    transport: HttpTransport
    timeout_seconds: int = 30

    def _require_configured(self) -> None:
        if not self.base_url or not self.service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")

    def _url(self, table: str) -> str:
        clean_table = str(table or "").strip().strip("/")
        if not SAFE_TABLE_NAME.fullmatch(clean_table):
            raise ValueError("A valid Supabase table name is required.")
        return f"{self.base_url.rstrip('/')}/rest/v1/{clean_table}"

    def _headers(self, prefer: str = DEFAULT_PREFER) -> dict[str, str]:
        return {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }

    @staticmethod
    def _optional_json(response) -> Any:
        if not str(getattr(response, "text", "") or "").strip():
            return None
        return response.json()

    def get_many(self, table: str, params: dict | None = None) -> list[dict]:
        self._require_configured()
        response = self.transport.get(
            self._url(table),
            headers=self._headers(),
            params=params or {},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Supabase list query returned a non-list response.")
        return payload

    def post(
        self,
        table: str,
        payload: dict | list,
        params: dict | None = None,
        prefer: str = DEFAULT_PREFER,
    ) -> Any:
        self._require_configured()
        response = self.transport.post(
            self._url(table),
            headers=self._headers(prefer),
            params=params or {},
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return self._optional_json(response)

    def patch(self, table: str, params: dict, payload: dict, prefer: str = "return=representation") -> Any:
        self._require_configured()
        response = self.transport.patch(
            self._url(table),
            headers=self._headers(prefer),
            params=params,
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return self._optional_json(response)

    def delete(self, table: str, params: dict) -> None:
        self._require_configured()
        response = self.transport.delete(
            self._url(table),
            headers=self._headers("return=minimal"),
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
