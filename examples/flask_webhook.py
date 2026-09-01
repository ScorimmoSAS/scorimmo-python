"""
Example: receive Scorimmo webhooks with Flask (API v2).

Install: pip install scorimmo[flask]
Run:     flask --app examples/flask_webhook run --port 3000

Env vars:
    SCORIMMO_WEBHOOK_SIGNATURE_SECRET  Secret HMAC-SHA256 partagé avec Scorimmo
                                        (facultatif — si non défini, aucune vérification
                                        n'est effectuée par le SDK et l'auth doit être
                                        gérée par le serveur/framework).

Idempotence : Scorimmo effectue jusqu'à 6 tentatives (retries exponentiels).
Dédupliquez par (event, lead_id, created_at/updated_at) côté récepteur.
"""
import os

from flask import Flask

from scorimmo import ScorimmoWebhook

app = Flask(__name__)

webhook = ScorimmoWebhook(
    signature_secret=os.environ.get("SCORIMMO_WEBHOOK_SIGNATURE_SECRET"),
    # signature_header="X-Signature-256",  # valeur par défaut, personnalisable
)


def on_new_lead(lead: dict) -> None:
    customer = lead.get("customer") or {}
    name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
    print(f"[new_lead] #{lead['id']} — {name} — {lead['interest']}")


def on_closure(event: dict) -> None:
    # V2 renvoie les libellés français : 'Succès', 'Fermé', 'Fermé par l'opérateur'
    reason = event.get("close_reason") or "—"
    print(f"[closure_lead] Lead #{event['lead_id']} — {event['status']}: {reason}")


def on_unknown(event: dict) -> None:
    # Événement futur (X-Scorimmo-Event = 'webhook.<name>')
    print(f"[scorimmo.unknown_event] {event}")


app.add_url_rule(
    "/webhook/scorimmo",
    view_func=webhook.flask_view({
        "new_lead": on_new_lead,
        "update_lead": lambda e: print(f"[update_lead] #{e['id']} at {e['updated_at']}"),
        "new_comment": lambda e: print(f"[new_comment] Lead #{e['lead_id']}: {e['comment']}"),
        "new_rdv": lambda e: print(f"[new_rdv] Lead #{e['lead_id']}: {e['start_time']}"),
        "new_reminder": lambda e: print(f"[new_reminder] Lead #{e['lead_id']}: {e['start_time']}"),
        "closure_lead": on_closure,
        "unknown": on_unknown,
    }),
    methods=["POST"],
)


if __name__ == "__main__":
    app.run(port=3000)
