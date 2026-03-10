from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


class ScorimmoWebhook:
    """Scorimmo webhook parser and dispatcher."""

    def __init__(self, header_value: str, header_key: str = "X-Scorimmo-Key") -> None:
        self._header_key = header_key.lower()
        self._header_value = header_value

    def parse(self, headers: dict[str, str], body: str | bytes | dict[str, Any]) -> dict[str, Any]:
        """
        Validates and parses an incoming webhook request.

        :param headers: HTTP headers (case-insensitive)
        :param body:    Raw JSON string, bytes, or already-parsed dict
        :raises WebhookAuthError:       On invalid or missing auth header
        :raises WebhookValidationError: On invalid payload
        """
        self._assert_auth(headers)

        if isinstance(body, (str, bytes)):
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as e:
                raise WebhookValidationError("Payload must be a valid JSON object") from e
        else:
            payload = body

        if not isinstance(payload, dict):
            raise WebhookValidationError("Payload must be a JSON object")

        if not payload.get("event") or not isinstance(payload["event"], str):
            raise WebhookValidationError('Missing or invalid "event" field in payload')

        return payload

    def dispatch(self, event: dict[str, Any], handlers: dict[str, Callable[[dict[str, Any]], None]]) -> None:
        """
        Dispatches a parsed event to the appropriate handler.

        Supported keys: new_lead, update_lead, new_comment, new_rdv, new_reminder, closure_lead, unknown
        """
        event_name = event.get("event", "unknown")
        handler = handlers.get(event_name) or handlers.get("unknown")
        if handler:
            handler(event)

    def handle(
        self,
        headers: dict[str, str],
        body: str | bytes | dict[str, Any],
        handlers: dict[str, Callable[[dict[str, Any]], None]],
    ) -> None:
        """Parse and dispatch in one call (convenience method)."""
        event = self.parse(headers, body)
        self.dispatch(event, handlers)

    def flask_view(self, handlers: dict[str, Callable[[dict[str, Any]], None]]) -> Callable[[], Any]:
        """
        Returns a Flask view function that handles Scorimmo webhooks.

        Usage:
            app.add_url_rule('/webhook', view_func=webhook.flask_view({
                'new_lead': lambda lead: crm.create(lead),
            }), methods=['POST'])
        """
        try:
            from flask import request, jsonify
        except ImportError as e:
            raise ImportError("Flask is required: pip install scorimmo[flask]") from e

        def view() -> Any:
            try:
                self.handle(dict(request.headers), request.get_data(), handlers)
                return jsonify({"ok": True}), 200
            except WebhookAuthError as e:
                return jsonify({"error": str(e)}), 401
            except WebhookValidationError as e:
                return jsonify({"error": str(e)}), 400

        return view

    def _assert_auth(self, headers: dict[str, str]) -> None:
        normalized = {k.lower(): v for k, v in headers.items()}
        received = normalized.get(self._header_key)
        if received != self._header_value:
            raise WebhookAuthError("Invalid or missing webhook authentication header")


class WebhookAuthError(Exception):
    pass


class WebhookValidationError(Exception):
    pass
