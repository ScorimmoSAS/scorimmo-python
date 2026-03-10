# scorimmo

SDK officiel Python pour la plateforme CRM immobilier [Scorimmo](https://pro.scorimmo.com).

Facilite l'intégration des leads Scorimmo dans votre CRM en deux modes :
- **Client API** — récupérez vos leads avec gestion automatique du token JWT
- **Réception de webhooks** — recevez et traitez les événements Scorimmo en temps réel

> **Documentation de référence :**
> [API REST](https://pro.scorimmo.com/api/doc) · [Webhooks](https://pro.scorimmo.com/webhook/doc)

---

## Sommaire

- [Installation](#installation)
- [Identifiants API](#identifiants-api)
- [Client API](#client-api)
- [Webhooks](#webhooks)
- [Intégration Flask](#intégration-flask)
- [Référence — Méthodes leads](#référence--méthodes-leads)
- [Référence — Événements webhook](#référence--événements-webhook)
- [Gestion des erreurs](#gestion-des-erreurs)
- [Support](#support)

---

## Installation

```bash
pip install scorimmo

# Avec support Flask
pip install scorimmo[flask]
```

**Prérequis :** Python ≥ 3.9

---

## Identifiants API

Les identifiants (`username` / `password`) sont les mêmes que ceux utilisés pour se connecter à [pro.scorimmo.com](https://pro.scorimmo.com).

Pour le webhook, le secret (`SCORIMMO_WEBHOOK_SECRET`) est une valeur que vous choisissez librement — communiquez-la ensuite à Scorimmo lors de la configuration (voir [Configurer le webhook chez Scorimmo](#configurer-le-webhook-chez-scorimmo)).

---

## Client API

### Initialisation

```python
from scorimmo import ScorimmoClient

client = ScorimmoClient(
    username="votre-identifiant",
    password="votre-mot-de-passe",
    # base_url="https://pro.scorimmo.com"  # par défaut
)
```

Le token JWT est géré automatiquement (récupéré et renouvelé à l'expiration).

### Récupérer les leads récents

```python
from datetime import datetime, timedelta, timezone

# Tous les leads des dernières 24 heures (pagination automatique)
since = datetime.now(timezone.utc) - timedelta(hours=24)
leads = client.leads.since(since)

# Depuis une date précise
leads = client.leads.since("2024-06-01 00:00:00")

# Leads modifiés récemment (plutôt que créés)
leads = client.leads.since(since, field="updated_at")
```

### Récupérer un lead par ID

```python
lead = client.leads.get(42)
```

### Rechercher des leads

```python
# Par ID externe (votre référence CRM)
result = client.leads.list(search={"external_lead_id": "MON-CRM-001"})

# Par email client
result = client.leads.list(search={"email": "client@exemple.com"})

# Avec tri et pagination
result = client.leads.list(
    search={"status": "new"},
    orderby="created_at",
    order="desc",
    limit=20,
    page=1,
)

# result["results"] contient les leads, result["total"] le nombre total
for lead in result["results"]:
    print(lead["id"], lead["customer"]["first_name"])
```

### Leads par point de vente

```python
result = client.leads.list_by_store(store_id=5, orderby="created_at", order="desc", limit=50)
```

---

## Webhooks

Les webhooks permettent à Scorimmo de notifier votre application en temps réel lors d'événements (nouveau lead, mise à jour, etc.).

### Initialisation

```python
import os
from scorimmo import ScorimmoWebhook

webhook = ScorimmoWebhook(
    header_value=os.environ["SCORIMMO_WEBHOOK_SECRET"],
    header_key="X-Scorimmo-Key",  # valeur par défaut, modifiable
)
```

### Traitement d'une requête entrante (générique)

```python
from scorimmo.exceptions import WebhookAuthError, WebhookValidationError

# headers : dict des en-têtes HTTP
# body    : corps brut de la requête (str, bytes ou dict déjà parsé)
try:
    webhook.handle(headers, body, {
        "new_lead": lambda event: on_new_lead(event),
        "update_lead": lambda event: on_update_lead(event),
        "new_comment": lambda event: on_new_comment(event),
        "new_rdv": lambda event: on_new_rdv(event),
        "new_reminder": lambda event: on_new_reminder(event),
        "closure_lead": lambda event: on_closure_lead(event),
        # Événement non reconnu (optionnel)
        "unknown": lambda event: print(f"Événement inconnu : {event['event']}"),
    })
    # Retourner HTTP 200
except WebhookAuthError:
    # Header d'authentification absent ou incorrect → retourner HTTP 401
    pass
except WebhookValidationError:
    # Payload JSON invalide ou champ "event" manquant → retourner HTTP 400
    pass
```

> **Important :** Scorimmo considère la livraison réussie uniquement si votre endpoint retourne HTTP 200. Tout autre code est ignoré.

### Configurer le webhook chez Scorimmo

Une fois votre endpoint déployé, transmettez les informations suivantes à votre **account manager Scorimmo** (voir [Support](#support)) :

```
URL du webhook : https://votre-app.com/webhook/scorimmo
En-tête d'authentification :
  Clé   : X-Scorimmo-Key
  Valeur : [votre SCORIMMO_WEBHOOK_SECRET]

Événements à activer :
  ☑ Nouveau lead        (new_lead)
  ☑ Mise à jour lead    (update_lead)
  ☑ Nouveau commentaire (new_comment)
  ☑ Rendez-vous         (new_rdv)
  ☑ Rappel              (new_reminder)
  ☑ Clôture lead        (closure_lead)

Point(s) de vente concerné(s) : [indiquez vos points de vente]
```

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
    header_value=os.environ["SCORIMMO_WEBHOOK_SECRET"],
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
    }),
    methods=["POST"],
)
```

La vue générée par `flask_view()` gère automatiquement les erreurs :
- Retourne `401` si le header d'authentification est absent ou incorrect
- Retourne `400` si le payload est invalide
- Retourne `{"ok": true}` avec HTTP 200 en cas de succès

---

## Référence — Méthodes leads

### `leads.get(lead_id: int) -> dict`

Retourne un lead complet par son ID Scorimmo.

### `leads.since(date: str | datetime, field: str = "created_at") -> list`

Retourne tous les leads créés (ou modifiés) après `date`. La pagination est gérée automatiquement — le résultat est une liste plate.

- `field` : `"created_at"` (défaut) ou `"updated_at"`

### `leads.list(search=None, orderby="id", order="desc", limit=20, page=1) -> dict`

Retourne une page de leads.

| Paramètre | Type | Description |
|---|---|---|
| `search` | `dict` | Filtres par champ (voir ci-dessous) |
| `orderby` | `str` | Champ de tri : `created_at`, `updated_at`, `status`, etc. |
| `order` | `str` | `"asc"` ou `"desc"` |
| `limit` | `int` | Nombre de résultats par page (défaut : 20) |
| `page` | `int` | Numéro de page (défaut : 1) |

**Filtres `search` disponibles :**

| Clé | Exemple |
|---|---|
| `id` | `{"id": "42"}` |
| `email` | `{"email": "client@exemple.com"}` |
| `status` | `{"status": "new"}` |
| `external_lead_id` | `{"external_lead_id": "MON-CRM-001"}` |
| `external_customer_id` | `{"external_customer_id": "CLIENT-456"}` |
| `created_at` | `{"created_at": ">2024-01-01"}` |
| `updated_at` | `{"updated_at": ">=2024-06-01 00:00:00"}` |

Les opérateurs de comparaison pour les dates : `>`, `>=`, `<`, `<=` (préfixe la valeur).

Retourne `{"results": [...], "total": N}`.

### `leads.list_by_store(store_id: int, **kwargs) -> dict`

Identique à `list()` mais limité à un point de vente spécifique. Accepte les mêmes paramètres nommés.

---

## Référence — Événements webhook

| Événement | Déclencheur | Champs principaux du payload |
|---|---|---|
| `new_lead` | Nouveau lead créé | Objet lead complet (`id`, `store_id`, `customer`, `interest`, `origin`, `seller`, `status`, `created_at`, …) |
| `update_lead` | Lead modifié | `id`, `updated_at`, champs modifiés uniquement |
| `new_comment` | Commentaire ajouté | `lead_id`, `comment`, `created_at` |
| `new_rdv` | Rendez-vous créé | `lead_id`, `start_time`, `location`, `detail` |
| `new_reminder` | Rappel créé | `lead_id`, `start_time`, `detail`, `type` (`offer` ou `recontact`) |
| `closure_lead` | Lead clôturé | `lead_id`, `status` (`SUCCESS`, `CLOSED`, `CLOSE_OPERATOR`), `close_reason` |

> Pour la structure complète de chaque payload, consultez la [documentation webhooks](https://pro.scorimmo.com/webhook/doc).

---

## Gestion des erreurs

```python
from scorimmo import ScorimmoApiError, ScorimmoAuthError
from scorimmo.exceptions import WebhookAuthError, WebhookValidationError

# Erreurs API
try:
    lead = client.leads.get(999)
except ScorimmoAuthError:
    # Identifiants incorrects ou token expiré
    print("Erreur d'authentification : vérifiez vos identifiants")
except ScorimmoApiError as e:
    print(f"Erreur API {e.status_code} : {e}")
    # Codes courants : 400 (requête invalide), 403 (accès refusé), 404 (lead inexistant)

# Erreurs webhook
try:
    event = webhook.parse(headers, body)
except WebhookAuthError:
    # Header absent ou valeur incorrecte → retourner HTTP 401
    pass
except WebhookValidationError:
    # JSON invalide ou champ "event" manquant → retourner HTTP 400
    pass
```

---

## Support

- Votre account manager Scorimmo
- [Formulaire de contact](https://pro.scorimmo.com/contact)
- [pro.scorimmo.com](https://pro.scorimmo.com)
