# scorimmo

SDK officiel Python pour la plateforme [Scorimmo](https://pro.scorimmo.com) — client API **v2** & récepteur webhook.

- **Client API** — récupérez, filtrez et mettez à jour vos leads avec gestion automatique du JWT (access + refresh token, rotation).
- **Réception de webhooks** — recevez les événements Scorimmo en temps réel, avec vérification optionnelle de la signature HMAC-SHA256.

> **Documentation de référence :**
> [API REST v2](https://pro.scorimmo.com/api/v2/doc) · [Webhooks](https://pro.scorimmo.com/webhook/doc)

---

## Sommaire

- [Installation](#installation)
- [Identifiants API](#identifiants-api)
- [Client API](#client-api)
- [Webhooks](#webhooks)
- [Intégration Flask](#intégration-flask)
- [Référence — Ressources](#référence--ressources)
- [Référence — Gestion des tokens](#référence--gestion-des-tokens)
- [Référence — Événements webhook](#référence--événements-webhook)
- [Gestion des erreurs](#gestion-des-erreurs)
- [Support](#support)

---

## Installation

```bash
pip install scorimmo

# Avec support Flask (vue webhook clé-en-main)
pip install scorimmo[flask]
```

**Prérequis :** Python ≥ 3.9

---

## Identifiants API

Les identifiants (`email` / `password`) sont ceux fournis par Scorimmo. L'identifiant est l'adresse email du compte API v2.

Après le premier appel authentifié, un **refresh token** est disponible via `get_refresh_token()`. Il permet de réinitialiser le client sans repasser par les identifiants (voir [Gestion des tokens](#référence--gestion-des-tokens)).

Pour le webhook, le secret HMAC (`SCORIMMO_WEBHOOK_SIGNATURE_SECRET`) est une valeur que vous choisissez librement — communiquez-la ensuite à Scorimmo lors de la configuration (voir [Configurer le webhook chez Scorimmo](#configurer-le-webhook-chez-scorimmo)).

---

## Client API

### Initialisation

**Avec identifiants email/password :**

```python
from scorimmo import ScorimmoClient

client = ScorimmoClient(
    email="votre-email",
    password="votre-mot-de-passe",
    # base_url="https://pro.scorimmo.com"  # par défaut
)
```

**Avec un refresh token persisté (sans exposer les identifiants) :**

```python
client = ScorimmoClient(refresh_token=persisted_token)
```

Le token JWT est géré automatiquement : refresh silencieux à l'expiration puis fallback sur email/password si nécessaire.

### Récupérer les leads récents

```python
from datetime import datetime, timedelta, timezone

# Tous les leads des dernières 24 heures — pagination + dédup automatiques
since = datetime.now(timezone.utc) - timedelta(hours=24)
leads = client.leads.since(since, include=["customer", "seller"])

# Depuis une date précise
leads = client.leads.since("2026-06-01 00:00:00")

# Leads modifiés récemment (plutôt que créés)
leads = client.leads.since(since, field="updated_at")

# Restreindre à un point de vente + callback de progression
leads = client.leads.since(
    since,
    store_id=776,
    include=["customer", "seller"],
    on_progress=lambda page, count, total, meta: print(f"Page {page}: {total} leads"),
)
```

### Récupérer un lead par ID

```python
lead = client.leads.get(42)
lead = client.leads.get(42, include=["customer", "seller", "appointments", "comments"])
```

### Rechercher des leads

```python
result = client.leads.list(
    interest="Transaction",
    store_id=1,
    **{"created_at[gte]": "2026-01-01T00:00:00+00:00"},
    sort="created_at:desc",
    limit=20,
)

# result["data"] contient les leads, result["meta"] contient la pagination
for lead in result["data"]:
    print(lead["id"], lead.get("customer_id"))
```

Filtres complets disponibles :

| Paramètre | Type | Description |
|---|---|---|
| `page` | `int` | Numéro de page (défaut : 1) |
| `limit` | `int` | Résultats par page (défaut : 10, max : 100) |
| `sort` | `str` | `"champ:asc"` ou `"champ:desc"` — champs : `id`, `created_at`, `updated_at`, `status` |
| `include` | `str` | Relations : `"customer,seller,appointments,reminders,requests,comments"` |
| `store_id` | `int` | Restreindre à un point de vente |
| `seller_id` | `int` | Restreindre à un conseiller |
| `status` | `str` | Statut du lead |
| `substatus` | `str` | Sous-statut |
| `interest` | `str` | `TRANSACTION`, `LOCATION`, `GESTION`… |
| `origin` | `str` | Origine du lead |
| `contact_type` | `str` | `physical`, `phone` ou `digital` |
| `purpose` | `str` | Achat, Location, Bailleur, Vente, Recherche, Locataire, Non renseigné |
| `customer_first_name` | `str` | Prénom du contact |
| `customer_last_name` | `str` | Nom du contact |
| `customer.email` | `str` | Email (à passer via `**{"customer.email": …}`) |
| `customer.phone` | `str` | Téléphone (OR sur phone/other_phone) |
| `external_lead_id` | `str` | Référence CRM |
| `requests_reference` | `str` | Référence du bien |
| `ids` | `str` | IDs multiples séparés par virgule |
| `created_at[gte\|lte\|eq]` | `str` | Filtres de date ISO 8601 |
| `updated_at[gte\|lte\|eq]` | `str` | Filtres de date ISO 8601 |

### Mise à jour partielle

```python
client.leads.update(42, {"external_lead_id": "CRM-456", "seller_id": 3533})
```

> **Création de leads :** volontairement non exposée par le SDK. Les leads doivent être créés via l'interface Scorimmo, un formulaire (`client.form.submit`), un webcallback ou un import.

---

## Webhooks

### Initialisation

L'authentification des webhooks est **optionnelle** — la sécurisation de l'endpoint est à la charge de l'intégrateur. Scorimmo propose plusieurs mécanismes complémentaires :

1. **Signature HMAC-SHA256** (fortement recommandé) — Scorimmo signe le corps brut avec un secret partagé et envoie la signature dans le header `X-Signature-256` sous la forme `sha256=<hex>`. Le SDK la vérifie en temps constant via `hmac.compare_digest()`.
2. **HTTP Basic auth via URL** — enregistrez le webhook comme `https://user:pass@host/path`, l'auth est déléguée au serveur/framework, transparente pour le SDK.
3. **Restriction réseau** (IP whitelist, VPN, mTLS…) — hors périmètre du SDK.

**Avec signature HMAC (recommandé) :**

```python
import os
from scorimmo import ScorimmoWebhook

webhook = ScorimmoWebhook(
    signature_secret=os.environ["SCORIMMO_WEBHOOK_SIGNATURE_SECRET"],
    # signature_header="X-Signature-256",  # valeur par défaut
)
```

**Sans vérification** (auth déportée sur le serveur) :

```python
webhook = ScorimmoWebhook()
```

> **Important :** si vous activez la signature, le corps brut doit être passé sous forme de `bytes` (ou `str`) **avant tout parsing JSON** — sinon la signature ne pourra pas être vérifiée. En Flask : `request.get_data()` ; en FastAPI : `await request.body()`.

### Traitement d'une requête entrante (générique)

```python
from scorimmo import WebhookAuthError, WebhookValidationError

# headers  : dict des en-têtes HTTP (str ou list, insensible à la casse)
# raw_body : corps brut de la requête (bytes recommandé)
try:
    webhook.handle(headers, raw_body, {
        "new_lead":     on_new_lead,
        "update_lead":  on_update_lead,
        "new_comment":  on_new_comment,
        "new_rdv":      on_new_rdv,
        "new_reminder": on_new_reminder,
        "closure_lead": on_closure_lead,
        # Événement futur inconnu (arrivé avec X-Scorimmo-Event: webhook.<name>) :
        "unknown":      lambda event: print(f"Événement inconnu : {event}"),
    })
    # → HTTP 200
except WebhookAuthError:
    # Signature manquante ou invalide → HTTP 401
    pass
except WebhookValidationError:
    # Payload JSON invalide ou champ "event" manquant → HTTP 400
    pass
```

### Headers webhook v2

Chaque requête webhook envoyée par Scorimmo inclut ces headers :

| Header | Exemple | Description |
|---|---|---|
| `X-Signature-256` | `sha256=8f4c…` | Signature HMAC-SHA256 du corps brut (présent si vous avez configuré un secret ; nom personnalisable) |
| `X-Scorimmo-Event` | `lead.created` | Nom sémantique de l'événement |
| `X-Scorimmo-Version` | `2026-04-20` | Version d'API (date, format `YYYY-MM-DD` — pas un numéro sémantique) |
| `User-Agent` | `Scorimmo/1.42.0` | Version applicative Scorimmo (distincte de `X-Scorimmo-Version`) |

```python
event_name  = webhook.get_semantic_event(headers)  # ex: 'lead.created'
api_version = webhook.get_api_version(headers)     # ex: '2026-04-20'
```

Correspondance entre le champ `event` du payload et `X-Scorimmo-Event` :

| `event` (payload) | `X-Scorimmo-Event` |
|---|---|
| `new_lead` | `lead.created` |
| `update_lead` | `lead.updated` |
| `closure_lead` | `lead.closed` |
| `new_comment` | `lead.comment_added` |
| `new_rdv` | `lead.appointment_created` |
| `new_reminder` | `lead.reminder_created` |
| _(événement futur inconnu)_ | `webhook.<name>` |

> Enregistrez un handler `'unknown'` pour capturer les événements futurs non encore modélisés — Scorimmo peut ajouter de nouveaux événements sans breaking change.

### Idempotence & retries

Scorimmo effectue jusqu'à **6 tentatives de livraison** (initial + 5 retries) avec backoff exponentiel (5 s → 60 s max). Le corps et la signature sont identiques à chaque retry.

Aucun `Idempotency-Key` n'est envoyé — votre receveur doit être idempotent, typiquement en dédupliquant sur `(event, lead_id, created_at)` ou `(event, id, updated_at)` selon le type d'événement.

### Configurer le webhook chez Scorimmo

Une fois votre endpoint déployé, transmettez les informations suivantes à votre **account manager Scorimmo** (voir [Support](#support)) :

```
URL du webhook : https://votre-app.com/webhook/scorimmo

Authentification (au choix, fortement recommandé) :
  Option A - Signature HMAC-SHA256
    Header : X-Signature-256   (nom personnalisable)
    Valeur : sha256=<hex(hmac_sha256(rawBody, secret))>
    Secret : [votre SCORIMMO_WEBHOOK_SIGNATURE_SECRET]

  Option B - HTTP Basic auth via URL
    URL : https://user:pass@votre-app.com/webhook/scorimmo

Événements à activer :
  ☑ Nouveau lead        (new_lead)
  ☑ Mise à jour lead    (update_lead)
  ☑ Nouveau commentaire (new_comment)
  ☑ Rendez-vous         (new_rdv)
  ☑ Rappel              (new_reminder)
  ☑ Clôture lead        (closure_lead)

Point(s) de vente concerné(s) : [indiquez vos points de vente]
```

> **Important :** Scorimmo considère la livraison réussie uniquement si votre endpoint retourne HTTP 200.

---

## Intégration Flask

```bash
pip install scorimmo[flask]
```

```python
import os
from flask import Flask
from scorimmo import ScorimmoWebhook

app = Flask(__name__)

webhook = ScorimmoWebhook(
    signature_secret=os.environ.get("SCORIMMO_WEBHOOK_SIGNATURE_SECRET"),
)

app.add_url_rule(
    "/webhook/scorimmo",
    view_func=webhook.flask_view({
        "new_lead":     lambda event: on_new_lead(event),
        "update_lead":  lambda event: on_update_lead(event),
        "new_comment":  lambda event: on_new_comment(event),
        "new_rdv":      lambda event: on_new_rdv(event),
        "new_reminder": lambda event: on_new_reminder(event),
        "closure_lead": lambda event: on_closure_lead(event),
        "unknown":      lambda event: log(event),
    }),
    methods=["POST"],
)
```

La vue générée par `flask_view()` :
- lit le corps brut via `request.get_data()` avant tout `json_decode()`,
- retourne `401` si la signature HMAC est absente ou invalide,
- retourne `400` si le payload est mal formé,
- retourne `{"ok": true}` avec HTTP 200 en cas de succès.

---

## Référence — Ressources

Toutes les ressources ci-dessous exposent `list(**query)` (et `get(id)` quand l'endpoint le permet).

### Leads — `client.leads`

Voir [Client API](#client-api) ci-dessus. Méthodes : `get`, `list`, `update`, `since`.

### Rendez-vous — `client.appointments`

| Paramètre | Type | Description |
|---|---|---|
| `lead_id` | `int` | Filtrer par lead |
| `ids` | `str` | IDs séparés par virgule |
| `created_at[gte\|lte\|eq]` | `str` | Filtres de date (ISO 8601) |
| `updated_at[gte\|lte]` | `str` | Idem |
| `start_time[gte\|lte\|eq]` | `str` | Idem |
| `sort` | `str` | `id`, `created_at`, `updated_at`, `start_time` (avec `:asc`/`:desc`) |

### Commentaires — `client.comments`

| Paramètre | Type | Description |
|---|---|---|
| `lead_id` | `int` | Filtrer par lead |
| `ids` | `str` | IDs séparés par virgule |
| `created_at[gte\|lte\|eq]` | `str` | Filtres de date |
| `sort` | `str` | `id`, `created_at` |

### Rappels — `client.reminders`

| Paramètre | Type | Description |
|---|---|---|
| `lead_id` | `int` | Filtrer par lead |
| `ids` | `str` | IDs séparés par virgule |
| `created_at[gte\|lte\|eq]` | `str` | Filtres de date |
| `updated_at[gte\|lte]` | `str` | Idem |
| `start_time[gte\|lte\|eq]` | `str` | Idem (`reminder_date` côté serveur) |
| `sort` | `str` | `id`, `created_at`, `updated_at`, `start_time` |

### Demandes — `client.requests`

| Paramètre | Type | Description |
|---|---|---|
| `lead_id` | `int` | Filtrer par lead |
| `reference` | `str` | Référence du bien |
| `ids` | `str` | IDs séparés par virgule |
| `created_at[gte\|lte\|eq]` | `str` | Filtres de date |
| `updated_at[gte\|lte]` | `str` | Idem |
| `sort` | `str` | `id`, `created_at`, `updated_at` |

### Contacts — `client.customers`

| Paramètre | Type | Description |
|---|---|---|
| `search` | `str` | Recherche full-text |
| `email` | `str` | Recherche par email |
| `phone` | `str` | Recherche par téléphone (OR sur phone/other_phone) |
| `sort` | `str` | `id` |

### Origines — `client.origins`

| Paramètre | Type | Description |
|---|---|---|
| `store_id` | `int` | Filtrer par point de vente |
| `has_tracking` | `bool` | `True` = origines avec au moins un traceur actif |
| `tracking_channel` | `str` | `phone` ou `email` (validé, sinon `ValueError`) |
| `include` | `str` | `tracking` pour inclure les numéros/emails traceurs |

### Utilisateurs — `client.users`

| Paramètre | Type | Description |
|---|---|---|
| `store_id` | `int` | Filtrer par point de vente |
| `interest` | `str` | Filtrer par intérêt |
| `role` | `str` | `admin`, `manager`, `agent` ou `virtual` (validé, sinon `ValueError`) |
| `sort` | `str` | `id`, `last_name`, `created_at` |

### Statuts — `client.status`

| Paramètre | Type | Description |
|---|---|---|
| `ids` | `str` | Liste d'ids séparés par virgule |
| `interest` | `str \| list` | Liste CSV d'intérêts (`"TRANSACTION,LOCATION"`) ou liste Python |
| `store_id` | `str \| list` | Idem pour les points de vente |

Réponse : `[{"label": "...", "sub_status": [...] | null}, …]`.

### Points de vente / Champs additionnels / Champs de demande

- `client.stores` — GET `/api/v2/stores`, GET `/api/v2/stores/{id}`
- `client.additional_fields` — GET `/api/v2/additional_fields` (`store_id`, `interest`)
- `client.request_fields` — GET `/api/v2/requests/fields` (`store_id`, `interest`)

### Formulaires publics — `client.form`

Soumission d'un formulaire de contact qui crée un lead et envoie un email au destinataire. **Scope requis : `ROLE_API_FORM_WRITE`** (à demander séparément de `lead:write`).

```python
response = client.form.submit({
    "store_id":   776,
    "libelle_id": 12,
    "to_email":   "contact@agence.fr",           # ou list de destinataires
    "origin":     "Site web",
    "message":    "Je souhaite visiter le bien X.",
    "subject":    "Demande de visite",           # optionnel
    "customer": {
        "civility":   "M.",
        "first_name": "Jean",
        "last_name":  "Dupont",
        "email":      "jean@example.com",
        "phone":      "0612345678",
    },
    "requests":          [{"...": "..."}],       # optionnel, labels du référentiel
    "additional_fields": [{"...": "..."}],       # optionnel, labels du référentiel
    "external_lead_id":  "CRM-12345",            # optionnel
})
# response == {"status": 200, "message": "email created", "id": 42, "store_id": 776, ...}
```

### Appels sortants — `client.web_callbacks`

Déclenche un appel depuis le PBX Scorimmo vers un numéro. **N'utilise pas** l'authentification Bearer : passez la clé personnelle `WebCallback` fournie par Scorimmo pour votre point de vente.

```python
client.web_callbacks.launch("votre-cle-wcb", "+33612345678")
# {"results": ["..."], "information": 200}
```

---

## Référence — Gestion des tokens

Le client gère automatiquement l'access token. À chaque expiration, il tente d'abord un refresh silencieux, puis bascule sur email/password si nécessaire.

```python
# 1. Premier démarrage — authentification par identifiants
client = ScorimmoClient(email="...", password="...")

# 2. Forcer l'auth initiale et récupérer le refresh token
client.get_token()
refresh_token = client.get_refresh_token()
# → persister refresh_token (cache Redis, base de données, coffre-fort…)

# 3. Démarrages suivants — sans identifiants
refresh_token = ...  # charger depuis le stockage
client = ScorimmoClient(refresh_token=refresh_token)

# 4. Après chaque session, le refresh token a tourné — le re-persister
client.get_token()
new_refresh_token = client.get_refresh_token()
# → mettre à jour le stockage
```

> **Rotation automatique :** chaque refresh token ne peut être utilisé qu'une seule fois. Le nouveau refresh token est disponible via `get_refresh_token()` après chaque renouvellement.

Méthodes disponibles :

- `client.get_token() -> str`
- `client.get_refresh_token() -> str | None`
- `client.refresh_access_token(refresh_token) -> dict`
- `client.revoke_token(refresh_token=None) -> dict` — `None` révoque tous les tokens du compte
- `client.validate_token() -> dict` — retourne `version`, `status`, `authenticated`, `scopes`, `stores_id`, `interests`

---

## Référence — Événements webhook

### `new_lead` — Nouveau lead reçu

Payload : objet lead complet — `id`, `store_id`, `interest`, `status`, `origin`, `contact_type`, `seller_present_on_creation`, `customer` (`first_name`, `last_name`, `email`, `phone`, `other_phone`, `pro`, `legal_name`, `former`…), `seller` (`id`, `first_name`, `last_name`, `email`, `is_virtual?`), `requests` (liste de biens avec clés en français : `"Type de bien"`, `"Prix"`, `"Surface"`, `"Ville"`, `"Code postal"`, `"Référence"`/`"Programme"`), `additional_fields`, `comments`, `external_lead_id?`, `external_customer_id?`.

### `update_lead` — Lead modifié

Payload **sparse** : `id`, `updated_at`, et uniquement les champs modifiés (même forme que ci-dessus mais partiel).

### `new_comment`

Payload : `lead_id`, `comment`, `created_at`, `external_lead_id?`.

### `new_rdv`

Payload : `lead_id`, `start_time`, `location`, `detail` (nullable — `Estimation`, `Découverte`, `Visite`, `Suivi`, `Proposition`, `Signature`), `comment`, `created_at`, `external_lead_id?`.

### `new_reminder`

Payload : `lead_id`, `start_time`, `detail` (`offer` ou `recontact`), `comment`, `created_at`, `external_lead_id?`.

### `closure_lead` — Lead clôturé

| Champ | Type | Description |
|---|---|---|
| `lead_id` | `int` | Identifiant du lead clôturé |
| `status` | `str` | Libellé du statut de clôture : `Succès` (vente/location conclue), `Fermé` (abandonné), `Fermé par l'opérateur` |
| `close_reason` | `str \| None` | Motif de clôture (présent quand `status` = `Fermé` ou `Succès`) |
| `external_lead_id` | `str \| None` | Référence CRM du lead, si renseignée |

```python
def on_closure_lead(event: dict) -> None:
    if event["status"] == "Succès":
        # Vente ou location conclue
        ...
```

> Pour la structure complète de chaque payload, consultez la [documentation webhooks](https://pro.scorimmo.com/webhook/doc).

---

## Gestion des erreurs

```python
from scorimmo import (
    ScorimmoApiError, ScorimmoAuthError,
    WebhookAuthError, WebhookValidationError,
)

# Erreurs API
try:
    lead = client.leads.get(999)
except ScorimmoAuthError:
    # Identifiants incorrects, refresh token révoqué, ou 401 sur endpoint non authentifié
    print("Erreur d'authentification")
except ScorimmoApiError as e:
    print(f"Erreur API {e.status_code} ({e.api_code}) : {e}")
    # Codes courants : 400 (VALIDATION_ERROR), 403 (FORBIDDEN), 404 (NOT_FOUND)

# Erreurs webhook
try:
    event = webhook.parse(headers, raw_body)
except WebhookAuthError:
    # Signature manquante ou invalide → HTTP 401
    pass
except WebhookValidationError:
    # JSON invalide ou champ "event" manquant → HTTP 400
    pass
```

---

## Support

- Votre account manager Scorimmo
- [Formulaire de contact](https://pro.scorimmo.com/contact)
- [pro.scorimmo.com](https://pro.scorimmo.com)
