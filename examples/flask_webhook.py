"""
Example: Receive Scorimmo webhooks with Flask

Install: pip install scorimmo[flask]
Run:     flask --app examples/flask_webhook run
"""
import os
from flask import Flask
from scorimmo import ScorimmoWebhook

app = Flask(__name__)

webhook = ScorimmoWebhook(
    header_value=os.environ.get("SCORIMMO_WEBHOOK_SECRET", "change-me"),
    header_key="X-Scorimmo-Key",
)

app.add_url_rule(
    "/webhook/scorimmo",
    view_func=webhook.flask_view({
        "new_lead": lambda lead: print(
            f"[new_lead] #{lead['id']} — "
            f"{lead.get('customer', {}).get('first_name', '')} "
            f"{lead.get('customer', {}).get('last_name', '')}"
        ),
        "update_lead": lambda e: print(f"[update_lead] #{e['id']} at {e['updated_at']}"),
        "new_comment": lambda e: print(f"[new_comment] Lead #{e['lead_id']}: {e['comment']}"),
        "new_rdv": lambda e: print(f"[new_rdv] Lead #{e['lead_id']}: {e['start_time']}"),
        "new_reminder": lambda e: print(f"[new_reminder] Lead #{e['lead_id']}: {e['start_time']}"),
        "closure_lead": lambda e: print(f"[closure_lead] Lead #{e['lead_id']}: {e['status']}"),
    }),
    methods=["POST"],
)

if __name__ == "__main__":
    app.run(port=3000)
