# scorimmo

SDK officiel Python pour la plateforme CRM immobilier [Scorimmo](https://pro.scorimmo.com).

Facilite l'intégration des leads Scorimmo dans votre CRM en deux modes :
- **Client API** — récupérez vos leads avec gestion automatique du token JWT
- **Réception de webhooks** — recevez et traitez les événements Scorimmo en temps réel

---

## Installation

```bash
pip install scorimmo

# Avec support Flask
pip install scorimmo[flask]
```

**Prérequis :** Python ≥ 3.9

---

## Client API

```python
from scorimmo import ScorimmoClient

client = ScorimmoClient(
    username="votre-identifiant-api",
    password="votre-mot-de-passe-api",
    # base_url="https://pro.scorimmo.com"  # par défaut
)

# Récupérer tous les leads des dernières 24h (pagination automatique)
from datetime import datetime, timedelta, timezone
since = datetime.now(timezone.utc) - timedelta(hours=24)
leads = client.leads.since(since)

# Récupérer un lead par son ID
lead = client.leads.get(42)

# Rechercher des leads
result = client.leads.list(search={"external_lead_id": "MON-CRM-001"}, limit=20)

# Leads d'un point de vente spécifique
store_leads = client.leads.list_by_store(1)
```

---

## Réception de webhooks

### 1. Exposer une route dans votre application

**Avec Flask :**

```python
from flask import Flask
from scorimmo import ScorimmoWebhook
import os

app = Flask(__name__)
webhook = ScorimmoWebhook(
    header_value=os.environ["SCORIMMO_WEBHOOK_SECRET"],
    header_key="X-Scorimmo-Key",
)

app.add_url_rule(
    "/webhook/scorimmo",
    view_func=webhook.flask_view({
        "new_lead":     lambda lead: crm.create_contact(lead),
        "update_lead":  lambda e:    crm.update_contact(e["id"], e),
        "new_comment":  lambda e:    crm.add_note(e["lead_id"], e["comment"]),
        "new_rdv":      lambda e:    crm.create_appointment(e),
        "new_reminder": lambda e:    crm.create_reminder(e),
        "closure_lead": lambda e:    crm.archive_contact(e["lead_id"]),
    }),
    methods=["POST"],
)
```

**Sans framework (générique) :**

```python
event = webhook.parse(request.headers, request.body)
webhook.dispatch(event, {
    "new_lead": lambda lead: ...,
})
```

### 2. Transmettre l'URL à Scorimmo

Une fois votre route déployée (ex. `https://votre-crm.com/webhook/scorimmo`), communiquez les informations suivantes à votre **account manager Scorimmo** ou par e-mail à **assistance@scorimmo.com** :

```
URL du webhook : https://votre-crm.com/webhook/scorimmo
En-tête d'authentification :
  Clé   : X-Scorimmo-Key
  Valeur : votre-secret

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

## Événements webhook

| Événement | Déclencheur | Champs principaux |
|-----------|-------------|-------------------|
| `new_lead` | Nouveau lead créé | Objet lead complet (client, biens, vendeur...) |
| `update_lead` | Lead modifié | `id`, champs modifiés uniquement |
| `new_comment` | Commentaire ajouté | `lead_id`, `comment`, `created_at` |
| `new_rdv` | Rendez-vous créé | `lead_id`, `start_time`, `location`, `detail` |
| `new_reminder` | Rappel créé | `lead_id`, `start_time`, `detail` |
| `closure_lead` | Lead clôturé | `lead_id`, `status`, `close_reason` |

---

## Gestion des erreurs

```python
from scorimmo import ScorimmoApiError, ScorimmoAuthError

try:
    lead = client.leads.get(999)
except ScorimmoApiError as e:
    print(e.status_code, str(e))  # ex: 404, "Lead not found"
except ScorimmoAuthError:
    print("Vérifiez vos identifiants API")
```

---

## Support

- Account manager Scorimmo
- **assistance@scorimmo.com**
- [pro.scorimmo.com](https://pro.scorimmo.com)
