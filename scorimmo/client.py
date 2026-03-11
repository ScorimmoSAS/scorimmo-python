from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx


class ScorimmoClient:
    """Official Scorimmo API client with automatic JWT token management."""

    def __init__(self, username: str, password: str, base_url: str = "https://pro.scorimmo.com") -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self.leads = LeadsResource(self)

    def get_token(self) -> str:
        """Returns a valid JWT token, fetching a new one if expired."""
        if self._token and self._token_expires_at and datetime.now(timezone.utc) < self._token_expires_at:
            return self._token

        response = httpx.post(
            f"{self._base_url}/api/login_check",
            json={"username": self._username, "password": self._password},
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            raise ScorimmoAuthError(f"Authentication failed: {response.status_code} {response.text}")

        data = response.json()
        self._token = data["token"]
        # Expire 60 seconds early to avoid edge cases
        raw_expiry = data["token_expirate_at"]
        if str(raw_expiry).isdigit():
            expires_at = datetime.fromtimestamp(int(raw_expiry), tz=timezone.utc)
        else:
            expires_at = datetime.fromisoformat(str(raw_expiry)).replace(tzinfo=timezone.utc)
        self._token_expires_at = expires_at - timedelta(seconds=60)

        return self._token

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """Authenticated JSON request. On a 401 the token cache is cleared and retried once."""
        try:
            return self._raw_request(method, path, body)
        except ScorimmoApiError as e:
            if e.status_code != 401:
                raise
            # Token expired server-side: invalidate cache and retry once with a fresh token
            self._token = None
            self._token_expires_at = None
            return self._raw_request(method, path, body)

    def _raw_request(self, method: str, path: str, body: Any = None) -> Any:
        response = httpx.request(
            method=method,
            url=f"{self._base_url}{path}",
            json=body,
            headers={
                "Authorization": f"Bearer {self.get_token()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if response.status_code < 200 or response.status_code >= 300:
            data = response.json() if response.content else {}
            raise ScorimmoApiError(
                message=data.get("message", response.reason_phrase),
                status_code=response.status_code,
                api_code=data.get("code"),
            )
        return response.json()


class LeadsResource:
    def __init__(self, client: ScorimmoClient) -> None:
        self._client = client

    def get(self, lead_id: int) -> dict[str, Any]:
        """Fetch a single lead by ID."""
        return self._client.request("GET", f"/api/lead/{lead_id}")

    def list(
        self,
        search: str | dict[str, str] | None = None,
        order: str = "desc",
        orderby: str = "id",
        limit: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """List leads with optional filtering, sorting and pagination."""
        params: list[tuple[str, str]] = []

        if isinstance(search, str):
            params.append(("search", search))
        elif isinstance(search, dict):
            for k, v in search.items():
                params.append((f"search[{k}]", v))

        params += [("order", order), ("orderby", orderby), ("limit", str(limit)), ("page", str(page))]
        qs = urlencode(params)

        return self._client.request("GET", f"/api/leads?{qs}")

    def since(
        self,
        date: str | datetime,
        field: str = "created_at",
        max_pages: int = 100,
        store_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch all leads created or updated after a given date.
        Automatically handles pagination and returns a flat deduplicated list.

        Args:
            store_id: Restrict to a specific store (/api/stores/{id}/leads); None = global
            max_pages: Safety cap on API pages fetched (default 100 → 5 000 leads)
        """
        iso = date.strftime("%Y-%m-%d %H:%M:%S") if isinstance(date, datetime) else date
        all_leads: list[dict[str, Any]] = []
        page = 1

        while True:
            query = dict(search={field: f">{iso}"}, order="asc", orderby=field, limit=50, page=page)
            result = self.list_by_store(store_id, **query) if store_id is not None else self.list(**query)

            results: list[dict[str, Any]] = result.get("results", [])
            infos = result.get("informations") or []
            total_items: int = infos[0].get("informations", {}).get("total_items", 0) if infos else 0

            all_leads.extend(results)
            page += 1

            if len(all_leads) >= total_items or not results or page > max_pages:
                break

        # Deduplicate by id — a lead can appear on two consecutive pages if it is
        # created or updated while pagination is in progress (boundary shift).
        seen: dict[int, dict[str, Any]] = {}
        for lead in all_leads:
            seen[lead["id"]] = lead
        return list(seen.values())

    def list_by_store(
        self,
        store_id: int,
        search: str | dict[str, str] | None = None,
        order: str = "desc",
        orderby: str = "id",
        limit: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """List leads for a specific store. Accepts the same parameters as list()."""
        params: list[tuple[str, str]] = []

        if isinstance(search, str):
            params.append(("search", search))
        elif isinstance(search, dict):
            for k, v in search.items():
                params.append((f"search[{k}]", v))

        params += [("order", order), ("orderby", orderby), ("limit", str(limit)), ("page", str(page))]
        qs = urlencode(params)

        return self._client.request("GET", f"/api/stores/{store_id}/leads?{qs}")


class ScorimmoApiError(Exception):
    def __init__(self, message: str, status_code: int, api_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_code = api_code


class ScorimmoAuthError(Exception):
    pass
