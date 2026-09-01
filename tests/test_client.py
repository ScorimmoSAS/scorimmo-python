from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from scorimmo.client import (
    FormResource,
    LeadsResource,
    OriginsResource,
    ScorimmoApiError,
    ScorimmoAuthError,
    ScorimmoClient,
    UsersResource,
    WebCallbacksResource,
)

BASE_URL = "https://pro.scorimmo.com"
ACCESS_TOKEN = "eyJhbGciOiJSUzI1NiJ9.access"
REFRESH_TOKEN = "refresh-abc"


def token_response(access: str = ACCESS_TOKEN, refresh: str = REFRESH_TOKEN, in_seconds: int = 3600) -> dict:
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=in_seconds)).isoformat()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": in_seconds,
        "expires_at": expires_at,
    }


def make_client(**overrides) -> ScorimmoClient:
    kwargs = dict(email="api@agence.fr", password="secret", base_url=BASE_URL)
    kwargs.update(overrides)
    return ScorimmoClient(**kwargs)


def make_page(data: list, page: int = 1, limit: int = 50, total: int | None = None) -> dict:
    total = total if total is not None else len(data)
    import math
    total_pages = max(1, math.ceil(total / limit))
    return {
        "data": data,
        "meta": {
            "limit": limit,
            "current_page": page,
            "total_items": total,
            "total_pages": total_pages,
            "previous_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        },
    }


# ── Construction ──────────────────────────────────────────────────────────────

def test_constructor_throws_without_any_credentials():
    with pytest.raises(ValueError):
        ScorimmoClient()


def test_constructor_accepts_email_and_password():
    client = ScorimmoClient(email="a@b.c", password="p")
    assert client is not None


def test_constructor_accepts_refresh_token_only():
    client = ScorimmoClient(refresh_token="r")
    assert client.get_refresh_token() == "r"


# ── Token flow ────────────────────────────────────────────────────────────────

@respx.mock
def test_get_token_authenticates_and_caches():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(
        return_value=httpx.Response(200, json=token_response())
    )
    client = make_client()
    assert client.get_token() == ACCESS_TOKEN
    assert client.get_token() == ACCESS_TOKEN  # cache
    assert respx.calls.call_count == 1


@respx.mock
def test_get_token_uses_refresh_token_before_credentials():
    respx.post(f"{BASE_URL}/api/v2/auth/refresh").mock(
        return_value=httpx.Response(200, json=token_response())
    )
    client = ScorimmoClient(refresh_token=REFRESH_TOKEN, base_url=BASE_URL)
    assert client.get_token() == ACCESS_TOKEN


@respx.mock
def test_get_token_falls_back_to_credentials_when_refresh_fails():
    respx.post(f"{BASE_URL}/api/v2/auth/refresh").mock(
        return_value=httpx.Response(401, json={"message": "revoked"})
    )
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(
        return_value=httpx.Response(200, json=token_response(access="new-access"))
    )
    client = make_client(refresh_token="stale")
    assert client.get_token() == "new-access"


@respx.mock
def test_auth_error_on_bad_credentials():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    client = make_client()
    with pytest.raises(ScorimmoAuthError):
        client.get_token()


@respx.mock
def test_refresh_access_token_updates_state():
    respx.post(f"{BASE_URL}/api/v2/auth/refresh").mock(
        return_value=httpx.Response(200, json=token_response(access="a2", refresh="r2"))
    )
    client = ScorimmoClient(refresh_token=REFRESH_TOKEN, base_url=BASE_URL)
    response = client.refresh_access_token(REFRESH_TOKEN)
    assert response["access_token"] == "a2"
    assert client.get_refresh_token() == "r2"


# ── Requests ──────────────────────────────────────────────────────────────────

@respx.mock
def test_leads_get_calls_v2_endpoint():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))
    respx.get(f"{BASE_URL}/api/v2/leads/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "interest": "TRANSACTION"})
    )
    client = make_client()
    lead = client.leads.get(42)
    assert lead["id"] == 42


@respx.mock
def test_leads_get_with_include():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))
    route = respx.get(url__startswith=f"{BASE_URL}/api/v2/leads/42").mock(
        return_value=httpx.Response(200, json={"id": 42})
    )
    client = make_client()
    client.leads.get(42, include=["customer", "seller"])
    # Le serveur URL-décode les %2C avant de router la query ; on vérifie donc les deux formes.
    url = str(route.calls[0].request.url)
    assert "include=customer,seller" in url or "include=customer%2Cseller" in url


@respx.mock
def test_leads_list_with_bracket_filters():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))
    route = respx.get(url__startswith=f"{BASE_URL}/api/v2/leads").mock(
        return_value=httpx.Response(200, json=make_page([{"id": 1}]))
    )
    client = make_client()
    client.leads.list(**{"created_at[gte]": "2026-01-01T00:00:00+00:00", "limit": 20})
    req_url = str(route.calls[0].request.url)
    assert "created_at[gte]=" in req_url
    assert "limit=20" in req_url


def test_leads_list_rejects_invalid_limit():
    client = make_client()
    with pytest.raises(ValueError):
        client.leads.list(limit=200)


def test_leads_list_rejects_invalid_page():
    client = make_client()
    with pytest.raises(ValueError):
        client.leads.list(page=0)


def test_leads_list_rejects_invalid_sort_field():
    client = make_client()
    with pytest.raises(ValueError):
        client.leads.list(sort="not_a_field:asc")


def test_leads_list_rejects_invalid_sort_direction():
    client = make_client()
    with pytest.raises(ValueError):
        client.leads.list(sort="id:sideways")


@respx.mock
def test_leads_update():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))
    respx.patch(f"{BASE_URL}/api/v2/leads/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "external_lead_id": "CRM-456"})
    )
    client = make_client()
    result = client.leads.update(42, {"external_lead_id": "CRM-456"})
    assert result["external_lead_id"] == "CRM-456"


def test_leads_update_rejects_empty_payload():
    client = make_client()
    with pytest.raises(ValueError):
        client.leads.update(42, {})


# ── since() ───────────────────────────────────────────────────────────────────

@respx.mock
def test_leads_since_paginates_and_dedupes():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))
    call_count = [0]

    def paginated(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        if call_count[0] == 1:
            return httpx.Response(200, json=make_page([{"id": 1}, {"id": 2}], page=1, limit=100, total=200))
        return httpx.Response(200, json=make_page([{"id": 2}, {"id": 3}], page=2, limit=100, total=200))

    respx.get(url__startswith=f"{BASE_URL}/api/v2/leads").mock(side_effect=paginated)
    client = make_client()
    leads = client.leads.since("2026-01-01")
    ids = sorted(l["id"] for l in leads)
    assert ids == [1, 2, 3]


@respx.mock
def test_leads_since_respects_max_pages():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))

    def responder(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        return httpx.Response(200, json=make_page([{"id": (page - 1) * 100 + i} for i in range(100)],
                                                  page=page, limit=100, total=1000))

    respx.get(url__startswith=f"{BASE_URL}/api/v2/leads").mock(side_effect=responder)
    client = make_client()
    leads = client.leads.since("2026-01-01", max_pages=2)
    assert len(leads) == 200


def test_leads_since_rejects_invalid_field():
    client = make_client()
    with pytest.raises(ValueError):
        client.leads.since("2026-01-01", field="not_a_field")


def test_leads_since_rejects_invalid_max_pages():
    client = make_client()
    with pytest.raises(ValueError):
        client.leads.since("2026-01-01", max_pages=0)


# ── Enum validation ──────────────────────────────────────────────────────────

def test_users_list_rejects_invalid_role():
    client = make_client()
    with pytest.raises(ValueError):
        client.users.list(role="root")


def test_origins_list_rejects_invalid_tracking_channel():
    client = make_client()
    with pytest.raises(ValueError):
        client.origins.list(tracking_channel="sms")


@respx.mock
def test_origins_list_accepts_boolean_has_tracking():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))
    route = respx.get(url__startswith=f"{BASE_URL}/api/v2/origins").mock(
        return_value=httpx.Response(200, json=make_page([]))
    )
    client = make_client()
    client.origins.list(has_tracking=True)
    assert "has_tracking=true" in str(route.calls[0].request.url)


# ── Form ──────────────────────────────────────────────────────────────────────

@respx.mock
def test_form_submit_posts_v2_endpoint():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))
    respx.post(f"{BASE_URL}/api/v2/form").mock(
        return_value=httpx.Response(201, json={"status": 200, "message": "email created", "id": 7,
                                                "store_id": 1, "libelle_id": 12, "origin": "web"})
    )
    client = make_client()
    result = client.form.submit({
        "store_id": 1, "libelle_id": 12, "to_email": "a@b.c",
        "origin": "web", "message": "hello",
    })
    assert result["id"] == 7


def test_form_submit_validates_required_fields():
    client = make_client()
    with pytest.raises(ValueError, match="store_id"):
        client.form.submit({"libelle_id": 1, "to_email": "a@b.c", "origin": "x", "message": "y"})


# ── WebCallbacks ─────────────────────────────────────────────────────────────

@respx.mock
def test_web_callbacks_launch_bypasses_bearer():
    route = respx.post(f"{BASE_URL}/api/v2/webcallbacks").mock(
        return_value=httpx.Response(200, json={"results": ["ok"], "information": 200})
    )
    client = ScorimmoClient(refresh_token="wontbeused", base_url=BASE_URL)
    result = client.web_callbacks.launch("wcb-key-42", "+33612345678")
    assert result["information"] == 200
    # Aucun Authorization header ne doit être envoyé.
    assert "authorization" not in {h.lower() for h in route.calls[0].request.headers.keys()}


def test_web_callbacks_launch_rejects_empty_params():
    client = make_client()
    with pytest.raises(ValueError):
        client.web_callbacks.launch("", "+33612345678")
    with pytest.raises(ValueError):
        client.web_callbacks.launch("k", "")


# ── Resources wiring ─────────────────────────────────────────────────────────

def test_all_resources_wired():
    client = make_client()
    assert isinstance(client.leads, LeadsResource)
    assert isinstance(client.form, FormResource)
    assert isinstance(client.web_callbacks, WebCallbacksResource)
    assert isinstance(client.users, UsersResource)
    assert isinstance(client.origins, OriginsResource)
    for attr in ("appointments", "comments", "reminders", "requests", "stores",
                 "customers", "status", "additional_fields", "request_fields"):
        assert hasattr(client, attr), attr


# ── Retry 401 ────────────────────────────────────────────────────────────────

@respx.mock
def test_request_retries_once_on_401_after_invalidating_token():
    # Première auth par credentials, puis réauth par refresh_token après invalidation.
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(
        return_value=httpx.Response(200, json=token_response(access="tok-1"))
    )
    respx.post(f"{BASE_URL}/api/v2/auth/refresh").mock(
        return_value=httpx.Response(200, json=token_response(access="tok-2"))
    )
    # Premier GET → 401 ; second GET (après réauth) → 200.
    respx.get(f"{BASE_URL}/api/v2/leads/42").mock(side_effect=[
        httpx.Response(401, json={"message": "token revoked"}),
        httpx.Response(200, json={"id": 42}),
    ])
    client = make_client()
    lead = client.leads.get(42)
    assert lead["id"] == 42
    # On a bien réauthentifié entre les deux GET (via refresh token).
    refresh_calls = [c for c in respx.calls if c.request.url.path == "/api/v2/auth/refresh"]
    assert len(refresh_calls) == 1
    get_calls = [c for c in respx.calls if c.request.url.path == "/api/v2/leads/42"]
    assert len(get_calls) == 2


@respx.mock
def test_request_does_not_retry_more_than_once_on_repeated_401():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(
        return_value=httpx.Response(200, json=token_response(access="tok-1"))
    )
    respx.post(f"{BASE_URL}/api/v2/auth/refresh").mock(
        return_value=httpx.Response(200, json=token_response(access="tok-2"))
    )
    respx.get(f"{BASE_URL}/api/v2/leads/42").mock(
        return_value=httpx.Response(401, json={"message": "still bad"})
    )
    client = make_client()
    with pytest.raises(ScorimmoApiError) as exc:
        client.leads.get(42)
    assert exc.value.status_code == 401
    # Deux GET seulement : l'appel initial + un unique retry.
    get_calls = [c for c in respx.calls if c.request.url.path == "/api/v2/leads/42"]
    assert len(get_calls) == 2


# ── expires_at / expires_in ──────────────────────────────────────────────────

@respx.mock
def test_apply_token_response_falls_back_to_expires_in_when_expires_at_missing():
    payload = {
        "access_token": ACCESS_TOKEN,
        "refresh_token": REFRESH_TOKEN,
        "token_type": "Bearer",
        "expires_in": 3600,
        # pas d'expires_at
    }
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=payload))
    client = make_client()
    assert client.get_token() == ACCESS_TOKEN
    # L'expiration doit être ~1h dans le futur (moins la marge de 60s), donc bien après now().
    assert client._token_expires_at is not None
    now = datetime.now(timezone.utc)
    assert client._token_expires_at > now + timedelta(minutes=50)
    assert client._token_expires_at < now + timedelta(minutes=61)


# ── Errors ───────────────────────────────────────────────────────────────────

@respx.mock
def test_api_error_on_404():
    respx.post(f"{BASE_URL}/api/v2/auth/token").mock(return_value=httpx.Response(200, json=token_response()))
    respx.get(f"{BASE_URL}/api/v2/leads/999").mock(
        return_value=httpx.Response(404, json={"code": "NOT_FOUND", "message": "Lead not found"})
    )
    client = make_client()
    with pytest.raises(ScorimmoApiError) as exc:
        client.leads.get(999)
    assert exc.value.status_code == 404
    assert exc.value.api_code == "NOT_FOUND"
