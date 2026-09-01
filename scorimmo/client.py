"""Client HTTP principal de l'API Scorimmo v2 + ressources exposées."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode

import httpx


# ── Client ────────────────────────────────────────────────────────────────────

class ScorimmoClient:
    """
    Client HTTP principal de l'API Scorimmo v2.

    Gère l'authentification JWT (access token + refresh token), le renouvellement automatique
    des tokens expirés et expose toutes les ressources de l'API v2.

    Authentification par identifiants ::

        client = ScorimmoClient(email="user@agence.fr", password="secret")

    Authentification par refresh token (sans exposer les identifiants) ::

        client = ScorimmoClient(refresh_token=persisted_token)
        # récupérer le nouveau refresh token après le premier appel :
        client.get_refresh_token()

    Ressources disponibles :
      * ``client.leads``             — Demandes de contact
      * ``client.appointments``      — Rendez-vous
      * ``client.comments``          — Commentaires et notes
      * ``client.reminders``         — Rappels / relances
      * ``client.requests``          — Biens recherchés ou proposés
      * ``client.stores``            — Points de vente
      * ``client.users``             — Conseillers et managers
      * ``client.customers``         — Contacts / prospects
      * ``client.status``            — Référentiel des statuts (labels + sous-statuts)
      * ``client.origins``           — Référentiel des origines
      * ``client.additional_fields`` — Champs additionnels par agence/intérêt
      * ``client.request_fields``    — Champs de demande par agence/intérêt
      * ``client.form``              — Soumission de formulaires publics (ROLE_API_FORM_WRITE)
      * ``client.web_callbacks``     — Déclenchement d'appels sortants (auth par clé WCB)
    """

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        base_url: str = "https://pro.scorimmo.com",
        *,
        refresh_token: str | None = None,
        timeout: float = 25.0,
        logger: logging.Logger | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if email is None and refresh_token is None:
            raise ValueError(
                "ScorimmoClient requires either email+password or a refresh_token."
            )

        self._email = email
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._logger = logger or logging.getLogger("scorimmo")

        self._access_token: str | None = None
        self._refresh_token: str | None = refresh_token
        self._token_expires_at: datetime | None = None

        self._http = http_client or httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

        # Resources
        self.leads = LeadsResource(self)
        self.appointments = AppointmentsResource(self)
        self.comments = CommentsResource(self)
        self.reminders = RemindersResource(self)
        self.requests = RequestsResource(self)
        self.stores = StoresResource(self)
        self.users = UsersResource(self)
        self.customers = CustomersResource(self)
        self.status = StatusResource(self)
        self.origins = OriginsResource(self)
        self.additional_fields = AdditionalFieldsResource(self)
        self.request_fields = RequestFieldsResource(self)
        self.form = FormResource(self)
        self.web_callbacks = WebCallbacksResource(self)

    # ── Token management ─────────────────────────────────────────────────────

    def get_token(self) -> str:
        """
        Retourne un access token valide.

        Ordre de priorité :

          1. Access token encore valide → retourné directement
          2. Refresh token disponible  → échangé contre un nouvel access token
          3. Email + password           → authentification complète

        Si le refresh token est rejeté et que des identifiants sont disponibles, le client
        bascule automatiquement sur l'authentification email/password.

        :raises ScorimmoAuthError: Si toutes les tentatives d'authentification échouent.
        """
        if (
            self._access_token is not None
            and self._token_expires_at is not None
            and self._token_expires_at > datetime.now(timezone.utc)
        ):
            return self._access_token

        if self._refresh_token is not None:
            try:
                self._exchange_refresh_token(self._refresh_token)
                assert self._access_token is not None
                return self._access_token
            except ScorimmoAuthError:
                if self._email is None:
                    raise
                self._logger.warning(
                    "[Scorimmo] Refresh token rejected, falling back to email/password auth"
                )
                self._refresh_token = None

        if self._email is None or self._password is None:
            raise ScorimmoAuthError(
                "Cannot authenticate: no valid refresh token and no email/password credentials provided."
            )

        self._logger.info("[Scorimmo] Obtaining new access token for %s", self._email)
        response = self._raw_request(
            "POST",
            "/api/v2/auth/token",
            {"email": self._email, "password": self._password},
            authenticate=False,
        )
        if "access_token" not in response:
            raise ScorimmoAuthError("Authentication failed: no access_token in response")
        self._apply_token_response(response)
        assert self._access_token is not None
        return self._access_token

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Échange explicitement un refresh token contre une nouvelle paire de tokens
        (POST /api/v2/auth/refresh) et met à jour l'état interne du client.

        Chaque refresh token ne peut être utilisé qu'une seule fois (rotation automatique).

        :raises ScorimmoAuthError: Si le refresh token est invalide ou révoqué.
        """
        return self._exchange_refresh_token(refresh_token)

    def get_refresh_token(self) -> str | None:
        """
        Retourne le refresh token courant (disponible après le premier appel authentifié).
        Utile pour persister la session et passer à :meth:`refresh_access_token` au prochain démarrage.
        """
        return self._refresh_token

    def revoke_token(self, refresh_token: str | None = None) -> dict[str, Any]:
        """
        Révoque un refresh token spécifique, ou tous les refresh tokens du compte si ``None``.

        :param refresh_token: ``None`` = révoquer tous les tokens.
        """
        self._logger.info("[Scorimmo] Revoking token(s), revoke_all=%s", refresh_token is None)
        body = (
            {"refresh_token": refresh_token}
            if refresh_token is not None
            else {"revoke_all": True}
        )
        return self._raw_request("POST", "/api/v2/auth/revoke", body, authenticate=False)

    def validate_token(self) -> dict[str, Any]:
        """
        Valide l'access token courant et retourne ses métadonnées.
        GET /api/v2/auth/validate.

        :returns: ``{version, status, authenticated, scopes, stores_id, interests}``.
        """
        return self.request("GET", "/api/v2/auth/validate")

    # ── HTTP requests ────────────────────────────────────────────────────────

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """
        Effectue une requête authentifiée vers l'API.

        Si l'API répond 401, on invalide le cache token et on retente UNE SEULE fois
        (le token en cache est peut-être révoqué côté serveur avant son ``expires_at``).

        :raises ScorimmoApiError:  Erreur HTTP renvoyée par l'API.
        :raises ScorimmoAuthError: Échec d'obtention/refresh de l'access token.
        """
        try:
            return self._raw_request(method, path, body, authenticate=True)
        except ScorimmoApiError as exc:
            if exc.status_code != 401:
                raise
            self._logger.warning(
                "[Scorimmo] 401 on authenticated request, invalidating cached token and retrying once"
            )
            self._access_token = None
            self._token_expires_at = None
            return self._raw_request(method, path, body, authenticate=True)

    def request_unauthenticated(self, method: str, path: str, body: Any = None) -> Any:
        """
        Effectue une requête sans authentification Bearer (utilisé par les endpoints qui
        portent leur propre mécanisme d'auth dans le body, ex : POST /api/v2/webcallbacks
        avec sa clé WCB).

        :raises ScorimmoApiError:  Erreur HTTP renvoyée par l'API.
        :raises ScorimmoAuthError: Réponse 401 renvoyée par l'endpoint.
        """
        return self._raw_request(method, path, body, authenticate=False)

    def close(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        self._http.close()

    def __enter__(self) -> "ScorimmoClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── Internals ────────────────────────────────────────────────────────────

    def _exchange_refresh_token(self, refresh_token: str) -> dict[str, Any]:
        self._logger.info("[Scorimmo] Refreshing access token")
        response = self._raw_request(
            "POST",
            "/api/v2/auth/refresh",
            {"refresh_token": refresh_token},
            authenticate=False,
        )
        if "access_token" not in response:
            raise ScorimmoAuthError("Token refresh failed: no access_token in response")
        self._apply_token_response(response)
        return response

    def _raw_request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        authenticate: bool = True,
    ) -> Any:
        headers: dict[str, str] = {}
        if authenticate:
            headers["Authorization"] = f"Bearer {self.get_token()}"

        method_upper = method.upper()
        self._logger.debug("[Scorimmo] → %s %s", method_upper, path)

        try:
            response = self._http.request(method_upper, path, json=body, headers=headers)
        except httpx.RequestError as e:
            self._logger.error("[Scorimmo] Transport error on %s %s: %s", method_upper, path, e)
            raise ScorimmoApiError(f"HTTP error: {e}", status_code=0) from e

        status = response.status_code
        self._logger.debug("[Scorimmo] ← %s %s %s", status, method_upper, path)

        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}

        if status < 200 or status >= 300:
            message = data.get("message") if isinstance(data, dict) else None
            message = message or response.reason_phrase or f"HTTP {status}"
            code = data.get("code") if isinstance(data, dict) else None

            if not authenticate and status == 401:
                raise ScorimmoAuthError(message)
            raise ScorimmoApiError(message, status_code=status, api_code=code)

        return data

    def _apply_token_response(self, response: dict[str, Any]) -> None:
        self._access_token = str(response["access_token"])
        self._refresh_token = (
            str(response["refresh_token"]) if "refresh_token" in response else None
        )
        raw_expiry = response.get("expires_at")
        if raw_expiry is None:
            # Repli : dériver expires_at depuis expires_in (secondes relatives à maintenant).
            expires_in = response.get("expires_in")
            if expires_in is None:
                raise ScorimmoAuthError(
                    "Token response is missing both 'expires_at' and 'expires_in'"
                )
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        elif isinstance(raw_expiry, (int, float)) or (isinstance(raw_expiry, str) and raw_expiry.isdigit()):
            expires_at = datetime.fromtimestamp(int(raw_expiry), tz=timezone.utc)
        else:
            expires_at = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        # Marge de 60s pour éviter les cas limites.
        self._token_expires_at = expires_at - timedelta(seconds=60)


# ── Abstract resource ─────────────────────────────────────────────────────────

class _AbstractResource:
    """
    Classe de base pour toutes les ressources de l'API Scorimmo v2.

    Fournit les opérations CRUD génériques (:meth:`get`, :meth:`list`), la validation des
    paramètres de pagination et le helper de query string. Chaque sous-classe déclare
    simplement son chemin de base via :attr:`base_path`.
    """

    base_path: str = ""
    sort_fields: tuple[str, ...] = ()

    def __init__(self, client: ScorimmoClient) -> None:
        self._client = client

    def get(self, resource_id: int, **query: Any) -> dict[str, Any]:
        """Récupère une ressource unique par son identifiant."""
        qs = self._build_query_string(query)
        path = f"{self.base_path}/{resource_id}" + (f"?{qs}" if qs else "")
        return self._client.request("GET", path)

    def list(self, **query: Any) -> dict[str, Any]:
        """
        Liste les ressources avec filtrage, tri et pagination optionnels.

        Paramètres communs : ``page`` (int, défaut 1), ``limit`` (int, 1–100, défaut 10),
        ``sort`` (str, format ``"field:asc|desc"``). La validation de ``limit``, ``page``
        et ``sort`` est appliquée automatiquement.

        :returns: ``{"data": [...], "meta": {...}}``.
        :raises ValueError: Si ``limit``, ``page`` ou ``sort`` ont une valeur invalide.
        """
        self._assert_valid_pagination(query)
        if "sort" in query and self.sort_fields:
            self._assert_valid_sort(str(query["sort"]), self.sort_fields)
        qs = self._build_query_string(query)
        return self._client.request("GET", self.base_path + (f"?{qs}" if qs else ""))

    # -- Validation -----------------------------------------------------------

    @staticmethod
    def _assert_valid_pagination(query: Mapping[str, Any]) -> None:
        if "limit" in query:
            limit = query["limit"]
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
                raise ValueError(f'"limit" must be an integer between 1 and 100, got: {limit!r}')
        if "page" in query:
            page = query["page"]
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                raise ValueError(f'"page" must be a positive integer (>= 1), got: {page!r}')

    @staticmethod
    def _assert_valid_sort(sort: str, valid_fields: Iterable[str]) -> None:
        parts = sort.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f'"sort" must be in format "field:direction", got: {sort!r}')
        field, direction = parts
        valid_list = list(valid_fields)
        if field not in valid_list:
            raise ValueError(
                f'"sort" field must be one of: {", ".join(valid_list)}. Got: {field!r}'
            )
        if direction not in ("asc", "desc"):
            raise ValueError(f'"sort" direction must be "asc" or "desc", got: {direction!r}')

    @staticmethod
    def _assert_enum(name: str, value: Any, allowed: Iterable[str]) -> None:
        allowed_list = list(allowed)
        if value not in allowed_list:
            raise ValueError(
                f'"{name}" must be one of: {", ".join(allowed_list)}. Got: {value!r}'
            )

    @staticmethod
    def _build_query_string(query: Mapping[str, Any]) -> str:
        """
        Encode un mapping clé-valeur en query string URL.

        Les valeurs ``None`` sont ignorées. Les booléens sont convertis en ``"true"``/``"false"``.
        Les listes sont converties en CSV. La notation bracket dans les clés
        (ex ``created_at[gte]``) est préservée non encodée afin que le serveur PHP parse
        correctement les filtres.
        """
        pairs: list[tuple[str, str]] = []
        for k, v in query.items():
            if v is None:
                continue
            if isinstance(v, bool):
                pairs.append((k, "true" if v else "false"))
            elif isinstance(v, (list, tuple)):
                pairs.append((k, ",".join(str(x) for x in v)))
            else:
                pairs.append((k, str(v)))
        return urlencode(pairs).replace("%5B", "[").replace("%5D", "]")


# ── Leads ────────────────────────────────────────────────────────────────────

class LeadsResource(_AbstractResource):
    """
    Ressource Leads — accès aux demandes de contact (mandats, acheteurs, locataires…).

    Endpoints couverts :

      * GET   /api/v2/leads         → :meth:`list`
      * GET   /api/v2/leads/{id}    → :meth:`get`
      * PATCH /api/v2/leads/{id}    → :meth:`update`

    La création de leads n'est volontairement pas exposée par le SDK : les leads doivent être
    créés via l'interface Scorimmo ou via un canal dédié (formulaires, webcallbacks, imports).
    """

    base_path = "/api/v2/leads"
    sort_fields = ("id", "created_at", "updated_at", "status")

    _DATE_FIELDS = ("created_at", "updated_at")
    _VALID_INCLUDES = ("customer", "seller", "appointments", "reminders", "requests", "comments")

    def get(self, resource_id: int, include: Iterable[str] | None = None) -> dict[str, Any]:
        """
        Récupère un lead unique par son identifiant.

        :param include: Relations à charger : ``customer``, ``seller``, ``appointments``,
                        ``reminders``, ``requests``, ``comments``.
        """
        query: dict[str, Any] = {}
        if include:
            query["include"] = ",".join(include)
        return super().get(resource_id, **query)

    def list(self, **query: Any) -> dict[str, Any]:
        """
        Liste les leads avec filtrage, tri et pagination.

        Filtres acceptés (voir README) : ``store_id``, ``seller_id``, ``status``,
        ``substatus``, ``interest``, ``origin``, ``contact_type``, ``purpose``,
        ``customer_first_name``, ``customer_last_name``, ``customer.email``,
        ``customer.phone``, ``external_lead_id``, ``requests_reference``, ``ids``,
        ``include``, et opérateurs bracket ``created_at[eq|gte|lte]`` /
        ``updated_at[eq|gte|lte]``.
        """
        return super().list(**query)

    def update(self, resource_id: int, data: Mapping[str, Any]) -> dict[str, Any]:
        """
        Mise à jour partielle d'un lead (seuls les champs transmis sont modifiés).

        Champs modifiables via PATCH : ``seller_id``, ``origin``, ``external_lead_id``,
        ``external_customer_id``, ``additional_fields`` (remplacement complet du bloc).
        """
        if not data:
            raise ValueError("update() requires at least one field to modify")
        return self._client.request("PATCH", f"{self.base_path}/{resource_id}", dict(data))

    def since(
        self,
        date: str | datetime,
        field: str = "created_at",
        max_pages: int = 100,
        store_id: int | None = None,
        include: Iterable[str] | None = None,
        on_progress: Callable[[int, int, int, dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Récupère tous les leads créés ou modifiés après une date donnée.
        Gère automatiquement la pagination et retourne une liste à plat dédupliquée.

        :param date:        ``datetime`` (heure préservée) ou ``str`` au format
                            ``Y-m-d``, ``Y-m-d H:i:s``, ou ISO 8601.
        :param field:       ``'created_at'`` (défaut) ou ``'updated_at'``.
        :param max_pages:   Nombre max de pages (défaut 100 ≈ 10 000 leads).
        :param store_id:    Restreindre à un point de vente ; ``None`` = tous.
        :param include:     Relations à charger (ex : ``["customer", "seller"]``).
        :param on_progress: Callback après chaque page :
                            ``fn(page, count, total, meta)``.

        :raises ValueError: Si ``date``, ``field`` ou ``max_pages`` ont une valeur invalide.
        """
        if field not in self._DATE_FIELDS:
            raise ValueError(
                f'"field" must be one of: {", ".join(self._DATE_FIELDS)}. Got: {field!r}'
            )
        if max_pages < 1:
            raise ValueError(f'"max_pages" must be >= 1, got: {max_pages}')

        if isinstance(date, datetime):
            iso = date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            iso = date

        all_leads: list[dict[str, Any]] = []
        page = 1

        while True:
            query: dict[str, Any] = {
                f"{field}[gte]": iso,
                "sort": f"{field}:asc",
                "limit": 100,
                "page": page,
            }
            if store_id is not None:
                query["store_id"] = store_id
            if include:
                query["include"] = ",".join(include)

            result = self.list(**query)
            results = result.get("data", []) or []
            all_leads.extend(results)

            if on_progress is not None:
                on_progress(page, len(results), len(all_leads), result.get("meta", {}) or {})

            meta = result.get("meta") or {}
            next_page = meta.get("next_page")
            page += 1

            if not next_page or not results or page > max_pages:
                break

        # Déduplique par id — un lead peut apparaître sur deux pages consécutives si la
        # liste se décale pendant la pagination (ex : nouveau lead créé entre deux appels).
        seen: dict[int, dict[str, Any]] = {}
        for lead in all_leads:
            if "id" in lead:
                seen[lead["id"]] = lead
        return list(seen.values())


# ── Read-only lead-related resources ──────────────────────────────────────────

class AppointmentsResource(_AbstractResource):
    """
    Ressource Appointments — rendez-vous rattachés aux leads.

    Endpoints couverts : GET /api/v2/appointments, GET /api/v2/appointments/{id}.
    Scope requis : ``lead:read``.
    """

    base_path = "/api/v2/appointments"
    sort_fields = ("id", "created_at", "updated_at", "start_time")


class CommentsResource(_AbstractResource):
    """
    Ressource Comments — commentaires et notes rattachés aux leads (notes système exclues).

    Endpoints couverts : GET /api/v2/comments, GET /api/v2/comments/{id}.
    Scope requis : ``lead:read``.
    """

    base_path = "/api/v2/comments"
    sort_fields = ("id", "created_at")


class RemindersResource(_AbstractResource):
    """
    Ressource Reminders — rappels / relances rattachés aux leads.

    Endpoints couverts : GET /api/v2/reminders, GET /api/v2/reminders/{id}.
    Scope requis : ``lead:read``.
    """

    base_path = "/api/v2/reminders"
    sort_fields = ("id", "created_at", "updated_at", "start_time")


class RequestsResource(_AbstractResource):
    """
    Ressource Requests — biens recherchés ou proposés rattachés aux leads.

    Endpoints couverts : GET /api/v2/requests, GET /api/v2/requests/{id}.
    Scope requis : ``lead:read``.
    """

    base_path = "/api/v2/requests"
    sort_fields = ("id", "created_at", "updated_at")


# ── Referential resources ─────────────────────────────────────────────────────

class StoresResource(_AbstractResource):
    """
    Ressource Stores — points de vente accessibles au compte API.

    Endpoints couverts : GET /api/v2/stores, GET /api/v2/stores/{id}.
    Scope requis : ``ref:read``.
    """

    base_path = "/api/v2/stores"
    sort_fields = ("id",)


class UsersResource(_AbstractResource):
    """
    Ressource Users — conseillers et managers des points de vente accessibles.

    Endpoints couverts : GET /api/v2/users, GET /api/v2/users/{id}.
    Scope requis : ``ref:read``.
    """

    base_path = "/api/v2/users"
    sort_fields = ("id", "last_name", "created_at")
    _ROLES = ("admin", "manager", "agent", "virtual")

    def list(self, **query: Any) -> dict[str, Any]:
        """
        Liste les utilisateurs avec filtrage optionnel.

        Filtres : ``store_id``, ``interest``, ``role`` (``admin`` / ``manager`` / ``agent``
        / ``virtual``).
        """
        if "role" in query and query["role"] is not None:
            self._assert_enum("role", query["role"], self._ROLES)
        return super().list(**query)


class CustomersResource(_AbstractResource):
    """
    Ressource Customers — contacts/prospects rattachés aux leads.

    Endpoints couverts : GET /api/v2/customers, GET /api/v2/customers/{id}.
    Scope requis : ``ref:read``.

    Le filtre ``phone`` s'applique en OR sur les colonnes ``phone`` et ``other_phone``
    côté API.
    """

    base_path = "/api/v2/customers"
    sort_fields = ("id",)


class StatusResource(_AbstractResource):
    """
    Ressource Status — référentiel des statuts et sous-statuts disponibles.

    Endpoints couverts : GET /api/v2/status.
    Scope requis : ``ref:read``.

    Retourne la liste paginée des statuts avec leurs sous-statuts associés. Exemple ::

        [{"label": "Succès", "sub_status": ["Loué", "Mandat"]}, ...]

    Les filtres ``interest`` et ``store_id`` acceptent une liste CSV (ex :
    ``"TRANSACTION,LOCATION"`` ou ``"1,2,3"``). Passer une ``list`` Python est également
    accepté (converti automatiquement en CSV).
    """

    base_path = "/api/v2/status"
    sort_fields = ("id",)


class OriginsResource(_AbstractResource):
    """
    Ressource Origins — origines configurées sur le compte.

    Endpoints couverts : GET /api/v2/origins.
    Scope requis : ``ref:read``.

    Utiliser le champ ``label`` retourné comme valeur du filtre ``origin`` dans
    :meth:`LeadsResource.list` et comme valeur du paramètre ``origin`` de POST /api/v2/form.
    """

    base_path = "/api/v2/origins"
    sort_fields = ("id",)
    _TRACKING_CHANNELS = ("phone", "email")

    def list(self, **query: Any) -> dict[str, Any]:
        """
        Liste les origines avec filtrage optionnel.

        Filtres : ``store_id``, ``has_tracking`` (bool → ``"true"``/``"false"``),
        ``tracking_channel`` (``phone`` / ``email``), ``include=tracking`` pour inclure
        les numéros/emails traceurs.
        """
        if "tracking_channel" in query and query["tracking_channel"] is not None:
            self._assert_enum("tracking_channel", query["tracking_channel"], self._TRACKING_CHANNELS)
        return super().list(**query)


class AdditionalFieldsResource(_AbstractResource):
    """
    Ressource Additional Fields — champs additionnels configurés par agence/intérêt.

    Endpoints couverts : GET /api/v2/additional_fields.
    Scope requis : ``ref:read``.
    """

    base_path = "/api/v2/additional_fields"


class RequestFieldsResource(_AbstractResource):
    """
    Ressource Request Fields — champs de demande configurés par agence/intérêt.

    Endpoints couverts : GET /api/v2/requests/fields.
    Scope requis : ``ref:read``.
    """

    base_path = "/api/v2/requests/fields"


# ── Public form + webcallbacks ────────────────────────────────────────────────

class FormResource(_AbstractResource):
    """
    Ressource Form — soumission de formulaires publics (POST /api/v2/form).

    Cet endpoint est destiné à recevoir des soumissions de formulaires depuis vos sites web
    (landing pages, formulaires de contact, portails partenaires). Il crée un lead dans le
    CRM après notification email au(x) destinataire(s) indiqué(s).

    Scope requis : ``ROLE_API_FORM_WRITE`` (à demander séparément de ``lead:write``).
    """

    base_path = "/api/v2/form"
    _REQUIRED = ("store_id", "libelle_id", "to_email", "origin", "message")

    def submit(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """
        Soumet un formulaire public. Crée un lead et envoie l'email au(x) destinataire(s).

        Champs requis : ``store_id``, ``libelle_id``, ``to_email``, ``origin``, ``message``.
        Champs optionnels : ``subject``, ``customer`` (civility ``M.``/``Mme``, first_name,
        last_name, email, phone), ``requests`` (liste de mappings
        label→valeur), ``additional_fields`` (idem), ``external_lead_id``.

        :returns: ``{"status": 200, "message": "email created", "id": ..., "store_id": ...,
                     "libelle_id": ..., "origin": ...}``.

        :raises ValueError: Si un champ requis est manquant.
        """
        for required in self._REQUIRED:
            if required not in data:
                raise ValueError(f'submit() requires "{required}" in payload')
        return self._client.request("POST", self.base_path, dict(data))


class WebCallbacksResource(_AbstractResource):
    """
    Ressource WebCallbacks — déclenche un appel sortant via l'API webcallback
    (POST /api/v2/webcallbacks).

    .. warning::
        Cet endpoint n'utilise PAS l'authentification Bearer classique. Il s'authentifie
        avec une clé personnelle « WebCallback » (paramètre ``key`` du body). Cette clé est
        distincte des credentials email/password de l'API et est configurée par point de vente.
    """

    base_path = "/api/v2/webcallbacks"

    def launch(self, key: str, number_to_call: str) -> dict[str, Any]:
        """
        Déclenche un appel sortant vers un numéro depuis le point de vente rattaché à la clé WCB.

        :param key:            Clé personnelle WebCallback (fournie par Scorimmo, distincte
                               du couple email/password).
        :param number_to_call: Numéro de téléphone destinataire au format international ou local.

        :returns: ``{"results": [...], "information": 200}``.

        :raises ValueError: Si l'un des deux paramètres est vide.
        """
        if not key or not number_to_call:
            raise ValueError('launch() requires both "key" and "number_to_call" to be non-empty')
        # Bypass de l'authentification Bearer : on passe par request_unauthenticated() —
        # le body porte lui-même la clé d'authentification (paramètre `key`).
        return self._client.request_unauthenticated(
            "POST",
            self.base_path,
            {"key": key, "number_to_call": number_to_call},
        )


# ── Exceptions ────────────────────────────────────────────────────────────────

class ScorimmoApiError(Exception):
    """
    Levée lorsque l'API Scorimmo renvoie une réponse HTTP non-2xx, ou lorsqu'une erreur
    réseau (timeout, DNS, connexion refusée) empêche d'atteindre l'API.

    :ivar status_code: Code HTTP renvoyé par l'API (``0`` pour une erreur réseau).
    :ivar api_code:    Identifiant d'erreur applicatif éventuellement retourné dans le
                       body JSON (ex : ``'VALIDATION_ERROR'``, ``'FORBIDDEN'``,
                       ``'NOT_FOUND'``, ou un entier).
    """

    def __init__(self, message: str, status_code: int, api_code: str | int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_code = api_code


class ScorimmoAuthError(Exception):
    """
    Levée lorsqu'une authentification API échoue : identifiants email/password rejetés,
    refresh token invalide ou révoqué, ou réponse 401 sur un endpoint non authentifié.
    """
