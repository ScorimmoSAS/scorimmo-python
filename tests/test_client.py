import pytest
import respx
import httpx
from datetime import datetime, timezone, timedelta
from scorimmo.client import ScorimmoClient, ScorimmoApiError, ScorimmoAuthError

BASE_URL = "https://app.scorimmo.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.test"
EXPIRES_AT = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
TOKEN_RESPONSE = {"token": TOKEN, "token_duration": 3600, "token_expirate_at": EXPIRES_AT}


def make_client() -> ScorimmoClient:
    return ScorimmoClient(BASE_URL, "api_user", "secret")


@respx.mock
def test_get_token_and_cache():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    client = make_client()
    t1 = client.get_token()
    t2 = client.get_token()
    assert t1 == TOKEN
    assert t2 == TOKEN
    assert respx.calls.call_count == 1  # Cached on second call


@respx.mock
def test_auth_error_on_bad_credentials():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(401, json={"message": "Bad credentials"}))
    client = make_client()
    with pytest.raises(ScorimmoAuthError):
        client.get_token()


@respx.mock
def test_leads_get():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    respx.get(f"{BASE_URL}/api/lead/42").mock(return_value=httpx.Response(200, json={"id": 42, "interest": "TRANSACTION"}))
    client = make_client()
    lead = client.leads.get(42)
    assert lead["id"] == 42


@respx.mock
def test_leads_list():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    respx.get(url__startswith=f"{BASE_URL}/api/leads").mock(
        return_value=httpx.Response(200, json={"results": [{"id": 1}, {"id": 2}], "total": 2, "page": 1, "limit": 20})
    )
    client = make_client()
    result = client.leads.list()
    assert len(result["results"]) == 2


@respx.mock
def test_leads_since_paginates():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    call_count = 0

    def paginated_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={"results": [{"id": 1}, {"id": 2}], "total": 3, "page": 1, "limit": 50})
        return httpx.Response(200, json={"results": [{"id": 3}], "total": 3, "page": 2, "limit": 50})

    respx.get(url__startswith=f"{BASE_URL}/api/leads").mock(side_effect=paginated_response)
    client = make_client()
    leads = client.leads.since("2024-01-01")
    assert len(leads) == 3
    assert [l["id"] for l in leads] == [1, 2, 3]


@respx.mock
def test_api_error_on_404():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    respx.get(f"{BASE_URL}/api/lead/999").mock(return_value=httpx.Response(404, json={"code": 404, "message": "Lead not found"}))
    client = make_client()
    with pytest.raises(ScorimmoApiError) as exc_info:
        client.leads.get(999)
    assert exc_info.value.status_code == 404
