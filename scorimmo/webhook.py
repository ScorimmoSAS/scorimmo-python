"""Réception et validation des webhooks Scorimmo (API v2)."""
from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import Any


class ScorimmoWebhook:
    """
    Réception et validation des webhooks Scorimmo (API v2).

    En V2, l'authentification des webhooks est **optionnelle** — la sécurisation de l'endpoint
    est à la charge de l'intégrateur. Trois mécanismes sont couramment utilisés (isolés ou combinés) :

      1. Signature HMAC-SHA256 (fortement recommandé) — Scorimmo signe le corps brut de la
         requête avec un secret partagé et envoie la signature dans un header dédié
         (par défaut ``X-Signature-256``, valeur ``sha256=<hex>``). Le SDK la vérifie en
         temps constant via :func:`hmac.compare_digest`.

      2. HTTP Basic auth via URL — l'endpoint est enregistré comme
         ``https://user:pass@host/path``. L'authentification est déléguée au serveur/framework,
         transparente pour le SDK.

      3. Restriction réseau (IP whitelist, VPN, mTLS…) — hors périmètre du SDK.

    Ce SDK gère uniquement le mécanisme 1. Pour l'activer, passer ``signature_secret`` au
    constructeur ; sinon, aucune vérification n'est effectuée et le payload est simplement parsé.

    Headers envoyés par Scorimmo sur chaque requête webhook :
      - {signature_header} : signature HMAC — présent uniquement si vous avez configuré un secret
      - ``X-Scorimmo-Event`` : nom sémantique de l'événement (ex : ``lead.created``)
      - ``X-Scorimmo-Version`` : date de version de l'API émettrice (ex : ``2026-04-20``)
      - ``User-Agent`` : ``Scorimmo/<app_version>`` (version applicative)

    Événements émis (valeurs du champ ``event`` du payload, mapping vers ``X-Scorimmo-Event``) ::

      new_lead       → lead.created
      update_lead    → lead.updated
      closure_lead   → lead.closed
      new_comment    → lead.comment_added
      new_rdv        → lead.appointment_created
      new_reminder   → lead.reminder_created

    Tout événement futur inconnu est diffusé sous la forme ``webhook.<internal_event>`` dans
    ``X-Scorimmo-Event`` ; le champ ``event`` du payload garde son nom interne. Les événements
    inconnus sont routés vers le handler spécial ``'unknown'`` s'il est enregistré, sinon ignorés.

    **Idempotence** : Scorimmo garantit une livraison at-least-once (jusqu'à 6 tentatives
    avec backoff exponentiel jusqu'à 60s). Le corps et la signature sont identiques à chaque
    retry. Le receveur doit donc être idempotent (dédupliquer par ``(event, lead_id, created_at)``).

    Utilisation avec signature HMAC (recommandé) ::

        webhook = ScorimmoWebhook(signature_secret=os.environ["SCORIMMO_WEBHOOK_SIGNATURE_SECRET"])
        webhook.handle(request.headers, request.get_data(),
                       {"new_lead": on_new_lead, "update_lead": on_update_lead})

    Utilisation sans vérification (auth déportée sur le serveur) ::

        webhook = ScorimmoWebhook()

    .. warning::
        Si vous activez la signature, le corps brut de la requête doit être passé sous forme
        de ``bytes`` (ou ``str``) **avant tout parsing JSON** — sinon la signature ne pourra
        pas être vérifiée. En Flask : ``request.get_data()`` ; en FastAPI : ``await request.body()``.
    """

    #: Préfixe conventionnel de la valeur de signature envoyée par Scorimmo.
    SIGNATURE_PREFIX = "sha256="

    #: Nom de header par défaut portant la signature HMAC.
    DEFAULT_SIGNATURE_HEADER = "X-Signature-256"

    def __init__(
        self,
        signature_secret: str | None = None,
        signature_header: str = DEFAULT_SIGNATURE_HEADER,
    ) -> None:
        # Un secret vide équivaut à ne pas vérifier — normalise en None pour éviter un
        # compare_digest silencieusement toujours faux si l'env var n'est pas renseignée.
        self._signature_secret: str | None = signature_secret if signature_secret else None
        self._signature_header: str = signature_header.lower()

    def parse(
        self,
        headers: Mapping[str, str | list[str]],
        raw_body: str | bytes,
    ) -> dict[str, Any]:
        """
        Valide et parse une requête webhook entrante.

        :param headers:  Headers HTTP (insensible à la casse ; accepte dict de str ou de list).
        :param raw_body: Corps JSON BRUT (``bytes`` recommandé, ``str`` accepté) — avant tout
                         parsing JSON, sinon la signature ne pourra pas être vérifiée.
        :returns:        Payload de l'événement parsé (dict).

        :raises WebhookAuthError:       Signature manquante ou invalide (uniquement si un
                                        secret a été configuré).
        :raises WebhookValidationError: Payload non valide (JSON malformé ou champ ``event`` manquant).
        """
        if self._signature_secret is not None:
            self._assert_signature(headers, raw_body)

        body_str = raw_body.decode("utf-8") if isinstance(raw_body, (bytes, bytearray)) else raw_body

        try:
            payload = json.loads(body_str)
        except json.JSONDecodeError as e:
            raise WebhookValidationError("Payload must be a valid JSON object") from e

        if not isinstance(payload, dict):
            raise WebhookValidationError("Payload must be a JSON object")

        event = payload.get("event")
        if not event or not isinstance(event, str):
            raise WebhookValidationError('Missing or invalid "event" field in payload')

        return payload

    def dispatch(
        self,
        event: dict[str, Any],
        handlers: Mapping[str, Callable[[dict[str, Any]], Any]],
    ) -> None:
        """
        Dispatche un événement parsé vers le handler correspondant.

        Clés supportées : ``new_lead``, ``update_lead``, ``new_comment``, ``new_rdv``,
        ``new_reminder``, ``closure_lead``. La clé spéciale ``'unknown'`` capture tous les
        événements non reconnus (utile pour recevoir les événements futurs émis en
        ``webhook.<name>``).
        """
        event_name = event.get("event", "unknown")
        handler = handlers.get(event_name) or handlers.get("unknown")
        if handler is not None:
            handler(event)

    def handle(
        self,
        headers: Mapping[str, str | list[str]],
        raw_body: str | bytes,
        handlers: Mapping[str, Callable[[dict[str, Any]], Any]],
    ) -> None:
        """Parse et dispatche un webhook en une seule opération (méthode de commodité)."""
        event = self.parse(headers, raw_body)
        self.dispatch(event, handlers)

    def verify_signature(
        self,
        raw_body: str | bytes,
        header_value: str,
        secret: str,
    ) -> bool:
        """
        Vérifie une signature HMAC-SHA256 en temps constant.

        Utilisable indépendamment de :meth:`parse` si vous souhaitez traiter la vérification
        vous-même (par exemple pour logger avant validation).

        :param raw_body:     Corps brut de la requête (``bytes`` ou ``str``).
        :param header_value: Valeur du header de signature (avec ou sans préfixe ``sha256=``).
        :param secret:       Secret partagé configuré côté Scorimmo.
        """
        received = (
            header_value[len(self.SIGNATURE_PREFIX):]
            if header_value.startswith(self.SIGNATURE_PREFIX)
            else header_value
        )
        body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else bytes(raw_body)
        expected = hmac.new(secret.encode("utf-8"), body_bytes, sha256).hexdigest()
        return hmac.compare_digest(expected, received)

    def verifies_signature(self) -> bool:
        """
        Indique si le webhook vérifie la signature HMAC des requêtes entrantes.
        ``False`` = aucun secret configuré, aucune vérification effectuée par le SDK.
        """
        return self._signature_secret is not None

    def get_semantic_event(self, headers: Mapping[str, str | list[str]]) -> str | None:
        """
        Extrait le nom sémantique de l'événement depuis le header ``X-Scorimmo-Event``.
        Utile pour logger ou router avant même de parser le payload.

        :returns: Ex : ``'lead.created'``, ``'webhook.<name>'`` pour un événement futur
                  inconnu, ou ``None`` si le header est absent.
        """
        return self._header_value(headers, "x-scorimmo-event")

    def get_api_version(self, headers: Mapping[str, str | list[str]]) -> str | None:
        """
        Extrait la version de l'API Scorimmo depuis le header ``X-Scorimmo-Version``.
        Il s'agit d'une date (format ``YYYY-MM-DD``), pas d'un numéro sémantique.

        :returns: Ex : ``'2026-04-20'``, ou ``None`` si le header est absent.
        """
        return self._header_value(headers, "x-scorimmo-version")

    def flask_view(
        self,
        handlers: Mapping[str, Callable[[dict[str, Any]], Any]],
    ) -> Callable[[], Any]:
        """
        Retourne une vue Flask qui parse le webhook et dispatche vers ``handlers``.

        Renvoie 401 sur signature invalide, 400 sur payload malformé, 200 sinon.

        Exemple ::

            app.add_url_rule('/webhook/scorimmo',
                             view_func=webhook.flask_view({'new_lead': on_new_lead}),
                             methods=['POST'])
        """
        try:
            from flask import jsonify, request
        except ImportError as e:  # pragma: no cover
            raise ImportError("Flask is required: pip install scorimmo[flask]") from e

        def view() -> Any:
            try:
                # request.get_data() renvoie le corps brut (bytes) — nécessaire pour la signature.
                self.handle(dict(request.headers), request.get_data(), handlers)
                return jsonify({"ok": True}), 200
            except WebhookAuthError as e:
                return jsonify({"error": str(e)}), 401
            except WebhookValidationError as e:
                return jsonify({"error": str(e)}), 400

        return view

    def _assert_signature(
        self,
        headers: Mapping[str, str | list[str]],
        raw_body: str | bytes,
    ) -> None:
        received = self._header_value(headers, self._signature_header)
        if received is None:
            raise WebhookAuthError(
                f'Missing webhook signature header "{self._signature_header}"'
            )
        assert self._signature_secret is not None  # narrowed by parse()
        if not self.verify_signature(raw_body, received, self._signature_secret):
            raise WebhookAuthError("Invalid webhook signature")

    @staticmethod
    def _header_value(
        headers: Mapping[str, str | list[str]],
        lower_key: str,
    ) -> str | None:
        """
        Lit une valeur de header insensible à la casse, en gérant à la fois les valeurs
        scalaires et les listes (Werkzeug/Starlette peuvent renvoyer les deux).
        """
        for k, v in headers.items():
            if k.lower() == lower_key:
                if isinstance(v, list):
                    return v[0] if v else None
                return str(v) if v is not None else None
        return None


class WebhookAuthError(Exception):
    """
    Levée par :meth:`ScorimmoWebhook.parse` lorsque la signature HMAC d'une requête webhook
    entrante est manquante ou invalide. À convertir en HTTP 401 côté récepteur.
    """


class WebhookValidationError(Exception):
    """
    Levée par :meth:`ScorimmoWebhook.parse` lorsque le corps de la requête webhook n'est pas
    un JSON valide, ou lorsque le champ obligatoire ``event`` est absent ou vide.
    À convertir en HTTP 400 côté récepteur.
    """
