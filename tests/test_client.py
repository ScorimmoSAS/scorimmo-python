import pytest
import respx
import httpx
from datetime import datetime, timezone, timedelta
from scorimmo.client import ScorimmoClient, ScorimmoApiError, ScorimmoAuthError

BASE_URL = "https://app.scorimmo.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.test"
# Unix timestamp (format réel renvoyé par l'API)
EXPIRES_AT = str(int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()))
TOKEN_RESPONSE = {"token": TOKEN, "token_duration": 3600, "token_expirate_at": EXPIRES_AT}


def make_client() -> ScorimmoClient:
    return ScorimmoClient(username="api_user", password="secret", base_url=BASE_URL)


def make_page(leads: list, total_items: int, page: int = 1, limit: int = 50) -> dict:
    import math
    return {
        "results": leads,
        "informations": [{
            "informations": {
                "limit": limit,
                "current_page": page,
                "total_items": total_items,
                "total_pages": math.ceil(total_items / limit),
                "current_page_results": len(leads),
                "previous_page": None,
                "next_page": None,
            }
        }],
    }


@respx.mock
def test_get_token_and_cache():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    client = make_client()
    t1 = client.get_token()
    t2 = client.get_token()
    assert t1 == TOKEN
    assert t2 == TOKEN
    assert respx.calls.call_count == 1


@respx.mock
def test_get_token_handles_unix_timestamp():
    unix_ts = str(int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()))
    respx.post(f"{BASE_URL}/api/login_check").mock(
        return_value=httpx.Response(200, json={**TOKEN_RESPONSE, "token_expirate_at": unix_ts})
    )
    client = make_client()
    assert client.get_token() == TOKEN


@respx.mock
def test_auth_error_on_bad_credentials():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(401, json={"message": "Bad credentials"}))
    client = make_client()
    with pytest.raises(ScorimmoAuthError):
        client.get_token()


@respx.mock
def test_request_retries_on_401():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    call_count = 0

    def lead_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(401, json={"message": "Token expired"})
        return httpx.Response(200, json={"id": 42, "interest": "TRANSACTION"})

    respx.get(f"{BASE_URL}/api/lead/42").mock(side_effect=lead_response)
    client = make_client()
    lead = client.leads.get(42)
    assert lead["id"] == 42
    assert call_count == 2


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
        return_value=httpx.Response(200, json=make_page([{"id": 1}, {"id": 2}], 2))
    )
    client = make_client()
    result = client.leads.list()
    assert len(result["results"]) == 2
    assert result["informations"][0]["informations"]["total_items"] == 2


@respx.mock
def test_leads_since_paginates():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    call_count = 0

    def paginated_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json=make_page([{"id": 1}, {"id": 2}], 3))
        return httpx.Response(200, json=make_page([{"id": 3}], 3, 2))

    respx.get(url__startswith=f"{BASE_URL}/api/leads").mock(side_effect=paginated_response)
    client = make_client()
    leads = client.leads.since("2024-01-01")
    assert len(leads) == 3
    assert [l["id"] for l in leads] == [1, 2, 3]


@respx.mock
def test_leads_since_deduplicates():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    call_count = 0

    def paginated_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json=make_page([{"id": 1}, {"id": 2}, {"id": 3}], 4))
        return httpx.Response(200, json=make_page([{"id": 3}, {"id": 4}], 4, 2))  # id 3 en double

    respx.get(url__startswith=f"{BASE_URL}/api/leads").mock(side_effect=paginated_response)
    client = make_client()
    leads = client.leads.since("2024-01-01")
    assert len(leads) == 4
    assert len({l["id"] for l in leads}) == 4


@respx.mock
def test_leads_since_respects_max_pages():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))

    def response(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        leads = [{"id": (page - 1) * 50 + i + 1} for i in range(50)]
        return httpx.Response(200, json=make_page(leads, 300, page))

    respx.get(url__startswith=f"{BASE_URL}/api/leads").mock(side_effect=response)
    client = make_client()
    leads = client.leads.since("2024-01-01", max_pages=2)
    assert len(leads) == 100


@respx.mock
def test_leads_since_uses_store_endpoint():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    store_mock = respx.get(url__startswith=f"{BASE_URL}/api/stores/776/leads").mock(
        return_value=httpx.Response(200, json=make_page([{"id": 1}], 1))
    )
    client = make_client()
    leads = client.leads.since("2024-01-01", store_id=776)
    assert len(leads) == 1
    assert store_mock.called


@respx.mock
def test_api_error_on_404():
    respx.post(f"{BASE_URL}/api/login_check").mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    respx.get(f"{BASE_URL}/api/lead/999").mock(return_value=httpx.Response(404, json={"code": 404, "message": "Lead not found"}))
    client = make_client()
    with pytest.raises(ScorimmoApiError) as exc_info:
        client.leads.get(999)
    assert exc_info.value.status_code == 404
