import hmac
import json
from hashlib import sha256

import pytest

from scorimmo.webhook import ScorimmoWebhook, WebhookAuthError, WebhookValidationError

HMAC_SECRET = "shared-secret-abc"

NEW_LEAD_PAYLOAD = json.dumps({
    "event": "new_lead",
    "id": 42,
    "store_id": 1,
    "created_at": "2026-06-01 10:00:00",
    "interest": "TRANSACTION",
    "customer": {"first_name": "Jean", "last_name": "Dupont"},
})


def sign(body: str, secret: str = HMAC_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body.encode(), sha256).hexdigest()


# ── Construction ──────────────────────────────────────────────────────────────

def test_constructor_accepts_no_secret():
    webhook = ScorimmoWebhook()
    assert webhook.verifies_signature() is False


def test_constructor_accepts_hmac_secret():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    assert webhook.verifies_signature() is True


def test_empty_string_secret_is_treated_as_unverified():
    webhook = ScorimmoWebhook(signature_secret="")
    assert webhook.verifies_signature() is False


# ── Signature disabled (no secret) ────────────────────────────────────────────

def test_parses_without_verifying_when_no_secret():
    webhook = ScorimmoWebhook()
    event = webhook.parse({}, NEW_LEAD_PAYLOAD)
    assert event["event"] == "new_lead"
    assert event["id"] == 42


def test_still_validates_payload_when_no_secret():
    webhook = ScorimmoWebhook()
    with pytest.raises(WebhookValidationError):
        webhook.parse({}, "not-json")


# ── HMAC signature enabled ────────────────────────────────────────────────────

def test_parses_valid_hmac_signed_payload():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    headers = {"x-signature-256": sign(NEW_LEAD_PAYLOAD)}
    event = webhook.parse(headers, NEW_LEAD_PAYLOAD)
    assert event["event"] == "new_lead"
    assert event["id"] == 42


def test_rejects_invalid_hmac_signature():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    with pytest.raises(WebhookAuthError):
        webhook.parse({"x-signature-256": "sha256=deadbeef"}, NEW_LEAD_PAYLOAD)


def test_rejects_missing_signature_header():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    with pytest.raises(WebhookAuthError):
        webhook.parse({}, NEW_LEAD_PAYLOAD)


def test_accepts_custom_signature_header():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET, signature_header="X-Custom-Sig")
    headers = {"x-custom-sig": sign(NEW_LEAD_PAYLOAD)}
    event = webhook.parse(headers, NEW_LEAD_PAYLOAD)
    assert event["event"] == "new_lead"


def test_accepts_signature_without_sha256_prefix():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    raw = hmac.new(HMAC_SECRET.encode(), NEW_LEAD_PAYLOAD.encode(), sha256).hexdigest()
    event = webhook.parse({"x-signature-256": raw}, NEW_LEAD_PAYLOAD)
    assert event["event"] == "new_lead"


def test_accepts_bytes_body():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    headers = {"x-signature-256": sign(NEW_LEAD_PAYLOAD)}
    event = webhook.parse(headers, NEW_LEAD_PAYLOAD.encode("utf-8"))
    assert event["id"] == 42


def test_accepts_header_value_as_list():
    # Starlette/Werkzeug peuvent renvoyer les headers sous forme de listes.
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    headers = {"x-signature-256": [sign(NEW_LEAD_PAYLOAD)]}
    event = webhook.parse(headers, NEW_LEAD_PAYLOAD)
    assert event["id"] == 42


def test_verify_signature_public_helper():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    sig = sign(NEW_LEAD_PAYLOAD)
    assert webhook.verify_signature(NEW_LEAD_PAYLOAD, sig, HMAC_SECRET) is True
    assert webhook.verify_signature(NEW_LEAD_PAYLOAD, sig[len("sha256="):], HMAC_SECRET) is True
    assert webhook.verify_signature(NEW_LEAD_PAYLOAD, "sha256=nope", HMAC_SECRET) is False
    assert webhook.verify_signature(NEW_LEAD_PAYLOAD + "tampered", sig, HMAC_SECRET) is False
    # bytes body accepté
    assert webhook.verify_signature(NEW_LEAD_PAYLOAD.encode(), sig, HMAC_SECRET) is True


# ── Payload validation ────────────────────────────────────────────────────────

def test_throws_on_invalid_json():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    with pytest.raises(WebhookValidationError):
        webhook.parse({"x-signature-256": sign("not-json")}, "not-json")


def test_throws_on_missing_event_field():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    body = json.dumps({"id": 1})
    with pytest.raises(WebhookValidationError):
        webhook.parse({"x-signature-256": sign(body)}, body)


# ── Dispatch ──────────────────────────────────────────────────────────────────

def test_dispatch_calls_correct_handler():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    event = webhook.parse({"x-signature-256": sign(NEW_LEAD_PAYLOAD)}, NEW_LEAD_PAYLOAD)
    called = []
    webhook.dispatch(event, {"new_lead": lambda e: called.append(e["event"])})
    assert called == ["new_lead"]


def test_dispatch_calls_unknown_handler_for_future_events():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    body = json.dumps({"event": "future_event", "lead_id": 1})
    event = webhook.parse({"x-signature-256": sign(body)}, body)
    called = []
    webhook.dispatch(event, {"unknown": lambda e: called.append(True)})
    assert called == [True]


def test_dispatch_does_not_throw_when_no_handler_registered():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    event = webhook.parse({"x-signature-256": sign(NEW_LEAD_PAYLOAD)}, NEW_LEAD_PAYLOAD)
    webhook.dispatch(event, {})  # should not raise


def test_handle_convenience_method():
    webhook = ScorimmoWebhook(signature_secret=HMAC_SECRET)
    received = []
    webhook.handle(
        {"x-signature-256": sign(NEW_LEAD_PAYLOAD)},
        NEW_LEAD_PAYLOAD,
        {"new_lead": lambda e: received.append(e["id"])},
    )
    assert received == [42]


# ── Header helpers ────────────────────────────────────────────────────────────

def test_get_semantic_event_reads_header():
    webhook = ScorimmoWebhook()
    assert webhook.get_semantic_event({"X-Scorimmo-Event": "lead.created"}) == "lead.created"
    assert webhook.get_semantic_event({"x-scorimmo-event": "webhook.some_future"}) == "webhook.some_future"
    assert webhook.get_semantic_event({}) is None


def test_get_api_version_reads_header():
    webhook = ScorimmoWebhook()
    assert webhook.get_api_version({"X-Scorimmo-Version": "2026-04-20"}) == "2026-04-20"
    assert webhook.get_api_version({}) is None
