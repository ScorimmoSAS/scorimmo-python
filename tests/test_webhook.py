import json
import pytest
from scorimmo.webhook import ScorimmoWebhook, WebhookAuthError, WebhookValidationError

webhook = ScorimmoWebhook("super-secret", "X-Api-Key")
valid_headers = {"x-api-key": "super-secret"}
new_lead_payload = json.dumps({
    "event": "new_lead", "id": 42, "store_id": 1,
    "created_at": "2024-06-01 10:00:00", "interest": "TRANSACTION",
    "customer": {"first_name": "Jean", "last_name": "Dupont"},
})


def test_parses_valid_payload():
    event = webhook.parse(valid_headers, new_lead_payload)
    assert event["event"] == "new_lead"
    assert event["id"] == 42


def test_throws_on_wrong_header_value():
    with pytest.raises(WebhookAuthError):
        webhook.parse({"x-api-key": "wrong"}, new_lead_payload)


def test_throws_on_missing_header():
    with pytest.raises(WebhookAuthError):
        webhook.parse({}, new_lead_payload)


def test_throws_on_invalid_json():
    with pytest.raises(WebhookValidationError):
        webhook.parse(valid_headers, "not-json")


def test_throws_on_missing_event_field():
    with pytest.raises(WebhookValidationError):
        webhook.parse(valid_headers, json.dumps({"id": 1}))


def test_case_insensitive_header_key():
    event = webhook.parse({"X-API-KEY": "super-secret"}, new_lead_payload)
    assert event["event"] == "new_lead"


def test_dispatch_calls_correct_handler():
    received = []
    event = webhook.parse(valid_headers, new_lead_payload)
    webhook.dispatch(event, {"new_lead": lambda e: received.append(e["event"])})
    assert received == ["new_lead"]


def test_dispatch_calls_unknown_handler():
    received = []
    payload = json.dumps({"event": "future_event", "lead_id": 1})
    event = webhook.parse(valid_headers, payload)
    webhook.dispatch(event, {"unknown": lambda e: received.append(True)})
    assert received == [True]


def test_dispatch_no_throw_when_no_handler():
    event = webhook.parse(valid_headers, new_lead_payload)
    webhook.dispatch(event, {})  # Should not raise


def test_handle_convenience_method():
    received = []
    webhook.handle(valid_headers, new_lead_payload, {
        "new_lead": lambda e: received.append(e["id"])
    })
    assert received == [42]


def test_accepts_dict_body():
    payload = {"event": "new_lead", "id": 1, "store_id": 1, "created_at": "2024-01-01", "interest": "TRANSACTION"}
    event = webhook.parse(valid_headers, payload)
    assert event["event"] == "new_lead"
