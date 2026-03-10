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
        expires_at = datetime.fromisoformat(data["token_expirate_at"]).replace(tzinfo=timezone.utc)
        self._token_expires_at = expires_at - timedelta(seconds=60)

        return self._token

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """Authenticated JSON request."""
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
    ) -> list[dict[str, Any]]:
        """
        Fetch all leads created or updated after a given date.
        Automatically handles pagination and returns a flat list.
        """
        if isinstance(date, datetime):
            iso = date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            iso = date

        all_leads: list[dict[str, Any]] = []
        page = 1

        while True:
            result = self.list(search={field: f">{iso}"}, order="asc", orderby=field, limit=50, page=page)
            results = result.get("results", [])
            total = result.get("total", 0)
            all_leads.extend(results)

            if len(all_leads) >= total or not results:
                break

            page += 1

        return all_leads

    def list_by_store(self, store_id: int, **kwargs: Any) -> dict[str, Any]:
        """List leads for a specific store."""
        params: list[tuple[str, str]] = []
        if "search" in kwargs and isinstance(kwargs["search"], dict):
            for k, v in kwargs["search"].items():
                params.append((f"search[{k}]", v))
        qs = urlencode(params) if params else ""
        return self._client.request("GET", f"/api/stores/{store_id}/leads" + (f"?{qs}" if qs else ""))

class ScorimmoApiError(Exception):
    def __init__(self, message: str, status_code: int, api_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_code = api_code


class ScorimmoAuthError(Exception):
    pass
